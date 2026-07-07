<template>
  <div class="pronunciation-question mt-3 mb-3">
    <h2 class="h7">Pronunciation</h2>
    <p class="prompt">{{ prompt }}</p>
    <p v-if="grading === 'score'" class="pron-provisional-banner alert alert-warning py-1 px-2">
      Provisional — channel-sensitive, treat as approximate.
    </p>

    <div v-if="!feedback" class="pron-recorder">
      <!-- IDLE -->
      <div v-if="state === 'idle'" class="pron-stage text-center">
        <button type="button" class="btn btn-primary pron-mic" @click="startRecording">
          <span class="pron-mic-dot"></span> Record
        </button>
        <p class="pron-hint small text-muted mt-2">
          Tap record and say the prompt aloud. Recording stops on its own when you finish.
        </p>
      </div>

      <!-- RECORDING -->
      <div v-else-if="state === 'recording'" class="pron-stage text-center">
        <div class="pron-live">
          <span class="pron-rec-dot"></span> Recording… {{ elapsedLabel }}
        </div>
        <div class="pron-meter" aria-hidden="true">
          <div class="pron-meter-fill" :style="{ width: meterWidth }"></div>
        </div>
        <button type="button" class="btn btn-outline-secondary btn-sm mt-2" @click="stopRecording">
          Stop
        </button>
        <p class="pron-hint small text-muted mt-1">Stops automatically after you stop speaking.</p>
      </div>

      <!-- RECORDED / SUBMITTING -->
      <div v-else-if="state === 'recorded' || state === 'submitting'" class="pron-stage text-center">
        <audio v-if="audioUrl" :src="audioUrl" controls class="pron-audio"></audio>
        <div v-if="state === 'submitting'" class="pron-submitting mt-2">Scoring your attempt…</div>
        <div v-else class="pron-actions mt-2">
          <button type="button" class="btn btn-primary" @click="submitForScoring">Submit for scoring</button>
          <button type="button" class="btn btn-link btn-sm ml-1" @click="reRecord">Re-record</button>
        </div>
      </div>
    </div>

    <div v-if="feedback" class="pron-feedback mt-2">
      <p v-if="feedback.status === 'scored'" class="pron-score">
        Provisional score: {{ Math.round(feedback.overall) }}/100
      </p>
      <div v-if="feedback.status === 'scored' && feedback.phoneme_scores && feedback.phoneme_scores.length"
           class="pron-phonemes mt-2">
        <div class="pron-phonemes-head small text-muted">Per-sound breakdown</div>
        <div class="pron-chips">
          <span v-for="(ps, i) in feedback.phoneme_scores" :key="i"
                class="pron-chip" :class="'pron-chip--' + chipBand(ps)" :title="chipTitle(ps)">
            <span class="pron-chip-sym">{{ friendlyLabel(ps.phoneme) }}</span>
            <span class="pron-chip-score">{{ chipScoreLabel(ps) }}</span>
          </span>
        </div>
        <div class="pron-phonemes-legend small text-muted mt-1">
          Each box is a speech sound in the word; the number is how close yours was. Grey = not judged confidently.
        </div>
      </div>
      <p v-else-if="feedback.status !== 'scored'" class="pron-neutral">
        Couldn't reliably score this attempt — you'll get full completion credit for trying.
      </p>
      <p v-if="feedback.weak_tags && feedback.weak_tags.length" class="pron-weak">
        Sounds to review: {{ feedback.weak_tags.join(', ') }}
      </p>
      <p class="pron-note small text-muted">
        Provisional feedback, not a graded evaluation. Scored on your device's mic.
      </p>
    </div>

    <p v-if="error" class="pron-error text-danger mt-1">{{ error }}</p>
  </div>
</template>

<script>
import axios from 'axios'
import { Mp3Encoder } from 'lamejs'

// --- Voice-activity / capture tuning (energy-based VAD, no ML dependency) ---
const MIN_MS = 700          // never auto-stop within the first 0.7s
const SILENCE_MS = 1200     // auto-stop after this much trailing silence (once speech started)
const MAX_MS = 20000        // hard cap on a single take
const SPEECH_RMS = 0.04     // energy above this counts as "the student is speaking"
const SILENCE_RMS = 0.018   // energy below this counts as silence
const MP3_KBPS = 128
const MIN_AUDIO_BYTES = 4000 // an empty/silent take encodes tiny; reject below this

// Learner-friendly labels for the engine's IPA phonemes: [chip label, tooltip
// description]. Beginners see the letter/digraph they know (with the sound nuance
// in the tooltip) instead of raw IPA. Fallback = the raw symbol.
const PHONEME_LABELS = {
  a: ['a', 'a'], b: ['b', 'b'], d: ['d', 'd'], e: ['e', 'e'], i: ['i', 'i'],
  j: ['y', 'y-glide (like bien)'], k: ['k', 'hard c / k'], l: ['l', 'l'],
  m: ['m', 'm'], n: ['n', 'n'], o: ['o', 'o'], p: ['p', 'p'],
  r: ['rr', 'rolled r (trill)'], s: ['s', 's'], t: ['t', 't'],
  'tʃ': ['ch', 'ch'], u: ['u', 'u'], w: ['w', 'w-glide (like agua)'],
  'ð': ['d', 'soft d (between vowels)'], 'ɡ': ['g', 'hard g'],
  'ɣ': ['g', 'soft g (between vowels)'], 'ɾ': ['r', 'tapped r (single flap)'],
  'ʝ': ['y', 'y / ll sound'], 'β': ['b', 'soft b / v (between vowels)'],
  y: ['u', 'rounded u (like tu)'], 'aː': ['a', 'long a'],
}
// Same IPA symbol, different spelling by language (French ou vs Spanish u).
const PHONEME_LABELS_FR = {
  u: ['ou', 'ou (like tout)'],
}

export default {
  name: 'PronunciationQuestion',
  props: {
    questionId: { type: Number, required: true },
    prompt: { type: String, required: true },
    problemJwt: { type: String, required: true },
    exerciseId: { type: String, required: true },
    language: { type: String, required: true },
    grading: { type: String, default: 'completion' },
    audioUploadUrl: { type: String, required: true },
    serviceUrl: { type: String, required: true },
    answerPostUrl: { type: String, default: '/api/jwt/process-answer-jwt' },
  },
  data() {
    return {
      state: 'idle',            // idle | recording | recorded | submitting
      feedback: null,
      error: null,
      level: 0,                 // live mic energy (0..1) for the meter
      elapsedMs: 0,
      audioUrl: null,           // object URL for playback
      audioBlob: null,          // encoded mp3 blob to submit
    };
  },
  computed: {
    meterWidth() {
      return Math.round(Math.min(1, this.level) * 100) + '%';
    },
    elapsedLabel() {
      const s = Math.floor(this.elapsedMs / 1000);
      return '0:' + String(s).padStart(2, '0');
    },
  },
  methods: {
    async startRecording() {
      this.error = null;
      if (!navigator.mediaDevices || !window.AudioContext && !window.webkitAudioContext) {
        this.error = 'Recording is not supported in this browser. Try desktop Chrome.';
        return;
      }
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
      } catch (e) {
        this.error = 'Microphone access was blocked. Allow the mic and try again.';
        return;
      }

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);

      this._stream = stream;
      this._ctx = ctx;
      this._source = source;
      this._processor = processor;
      this._sampleRate = ctx.sampleRate;
      this._pcm = [];
      this._speechStarted = false;
      this._silenceStart = 0;
      this._recStart = (window.performance && performance.now()) || Date.now();

      processor.onaudioprocess = (ev) => {
        const input = ev.inputBuffer.getChannelData(0);
        // Keep a copy of the samples for mp3 encoding on stop.
        this._pcm.push(new Float32Array(input));

        // Energy (RMS) for the meter and the VAD.
        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        const rms = Math.sqrt(sum / input.length);
        this.level = Math.min(1, rms * 8);

        const now = (window.performance && performance.now()) || Date.now();
        const elapsed = now - this._recStart;
        if (rms > SPEECH_RMS) this._speechStarted = true;
        if (this._speechStarted) {
          if (rms < SILENCE_RMS) {
            if (!this._silenceStart) this._silenceStart = now;
            else if (now - this._silenceStart >= SILENCE_MS && elapsed >= MIN_MS) {
              this.stopRecording();
              return;
            }
          } else {
            this._silenceStart = 0;
          }
        }
        if (elapsed >= MAX_MS) this.stopRecording();
      };

      source.connect(processor);
      // Connect to destination so onaudioprocess fires; we never write output, so it's silent (no echo).
      processor.connect(ctx.destination);

      this.state = 'recording';
      this.elapsedMs = 0;
      this._elapsedTimer = setInterval(() => {
        const now = (window.performance && performance.now()) || Date.now();
        this.elapsedMs = now - this._recStart;
      }, 200);
    },

    stopRecording() {
      if (this.state !== 'recording') return;
      this._teardownAudio();

      const blob = this._encodeMp3(this._pcm, this._sampleRate);
      this._pcm = [];
      if (!blob || blob.size < MIN_AUDIO_BYTES || !this._speechStarted) {
        this.error = "We didn't catch any audio — record again and speak clearly.";
        this.state = 'idle';
        this.level = 0;
        return;
      }
      if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
      this.audioBlob = blob;
      this.audioUrl = URL.createObjectURL(blob);
      this.state = 'recorded';
      this.level = 0;
    },

    reRecord() {
      if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
      this.audioUrl = null;
      this.audioBlob = null;
      this.error = null;
      this.state = 'idle';
    },

    // Per-phoneme chip helpers (mirror johnny-lingo-v2 bands: >=75 good, >=60 ok,
    // else bad; suppressed when the model isn't confident on that sound).
    chipSuppressed(ps) {
      return !ps || ps.reliable === false || ps.abstain === true || ps.score == null;
    },
    chipBand(ps) {
      if (this.chipSuppressed(ps)) return 'na';
      if (ps.score >= 75) return 'good';
      if (ps.score >= 60) return 'ok';
      return 'bad';
    },
    chipScoreLabel(ps) {
      return this.chipSuppressed(ps) ? '–' : Math.round(ps.score);
    },
    phonemeInfo(sym) {
      const fr = this.language === 'fr' ? PHONEME_LABELS_FR[sym] : null;
      return fr || PHONEME_LABELS[sym] || [sym, sym];
    },
    friendlyLabel(sym) {
      return this.phonemeInfo(sym)[0];
    },
    chipTitle(ps) {
      const desc = this.phonemeInfo(ps.phoneme)[1];
      if (this.chipSuppressed(ps)) return desc + ' — not judged confidently';
      const band = ps.band != null ? ' ±' + Math.round(ps.band) : '';
      return desc + ' — ' + Math.round(ps.score) + band;
    },

    _teardownAudio() {
      if (this._elapsedTimer) { clearInterval(this._elapsedTimer); this._elapsedTimer = null; }
      if (this._processor) { try { this._processor.disconnect(); this._processor.onaudioprocess = null; } catch (e) {} }
      if (this._source) { try { this._source.disconnect(); } catch (e) {} }
      if (this._stream) { this._stream.getTracks().forEach((t) => t.stop()); this._stream = null; }
      if (this._ctx) { try { this._ctx.close(); } catch (e) {} this._ctx = null; }
    },

    _encodeMp3(chunks, sampleRate) {
      let total = 0;
      for (const c of chunks) total += c.length;
      if (!total) return null;
      const pcm = new Int16Array(total);
      let off = 0;
      for (const c of chunks) {
        for (let i = 0; i < c.length; i++) {
          const s = Math.max(-1, Math.min(1, c[i]));
          pcm[off++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
      }
      const enc = new Mp3Encoder(1, sampleRate, MP3_KBPS);
      const block = 1152;
      const data = [];
      for (let i = 0; i < pcm.length; i += block) {
        const buf = enc.encodeBuffer(pcm.subarray(i, i + block));
        if (buf.length > 0) data.push(new Int8Array(buf));
      }
      const end = enc.flush();
      if (end.length > 0) data.push(new Int8Array(end));
      return new Blob(data, { type: 'audio/mpeg' });
    },

    async submitForScoring() {
      if (!this.audioBlob) { this.error = 'Record an attempt first.'; return; }
      this.error = null;
      this.state = 'submitting';

      // 1) Upload the mp3 to ADAPT (axios carries the app's auth like every other API call).
      let uploadData = null;
      try {
        const form = new FormData();
        form.append('audio', this.audioBlob, 'attempt.mp3');
        const upload = await axios.post(this.audioUploadUrl, form);
        uploadData = upload && upload.data;
      } catch (e) {
        this.error = 'Upload failed; please try again.';
        this.state = 'recorded';
        return;
      }
      const audioUrl = uploadData && uploadData.submission_file_url;
      if (!audioUrl) {
        this.error = 'Upload failed; please try again.';
        this.state = 'recorded';
        return;
      }

      // 2) Score + gradeback.
      await this.scoreAudio(audioUrl, uploadData);
    },

    async scoreAudio(audioUrl, uploadData) {
      // uploadData carries submission_file_url + date_submitted; the gradeback response from
      // /api/jwt/process-answer-jwt carries {type, message, completed_all_assignment_questions}
      // (see Submission::store). The parent's submittedPronunciation handler uses upload.* for the
      // file fields and response.* for the modal/type/completion fields.
      try {
        const r = await fetch(this.serviceUrl + '/score', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            problemJWT: this.problemJwt,
            exercise_id: this.exerciseId,
            language: this.language,
            audio_url: audioUrl,
          }),
        });
        if (!r.ok) throw new Error('scoring service error');
        const data = await r.json();
        this.feedback = data.feedback;
        // Post the signed answerJWT to the gradebook (mirrors WeBWorK). The gradebook trusts
        // only this signed token; the inline feedback is display-only.
        const gradeback = await fetch(this.answerPostUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/jwt' },
          body: data.answerJWT,
        });
        const gradebackJson = await gradeback.json();
        this.$emit('scored', { response: gradebackJson, upload: uploadData });
      } catch (e) {
        // Display-only fallback; the gradebook still awards completion credit via the service's
        // completion answerJWT. If even that failed, the audio is in S3 for an instructor to resolve.
        this.feedback = { status: 'unscoreable', weak_tags: [] };
        this.error = 'Could not score your attempt; you will get completion credit.';
      }
    },
  },
  beforeDestroy() {
    this._teardownAudio();
    if (this.audioUrl) URL.revokeObjectURL(this.audioUrl);
  },
};
</script>

<style scoped>
.pron-recorder {
  max-width: 420px;
  margin: 0 auto;
  padding: 16px;
  background: #f7f8fa;
  border: 1px solid #e6e8ec;
  border-radius: 12px;
}
.pron-mic {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.pron-mic-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  display: inline-block;
}
.pron-live {
  font-weight: 600;
  color: #c0392b;
}
.pron-rec-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #e74c3c;
  margin-right: 6px;
  animation: pron-pulse 1s ease-in-out infinite;
}
@keyframes pron-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
.pron-meter {
  height: 8px;
  background: #e6e6e6;
  border-radius: 5px;
  overflow: hidden;
  margin: 10px auto 0;
  max-width: 260px;
}
.pron-meter-fill {
  height: 100%;
  background: #16a085;
  transition: width 0.1s linear;
}
.pron-audio {
  width: 100%;
  max-width: 320px;
  height: 40px;
}
.pron-hint {
  margin-bottom: 0;
}
.pron-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.pron-chip {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  min-width: 34px;
  padding: 3px 7px;
  border-radius: 8px;
  border: 1px solid transparent;
  line-height: 1.15;
}
.pron-chip-sym {
  font-size: 15px;
  font-weight: 600;
}
.pron-chip-score {
  font-size: 10px;
  opacity: 0.85;
}
.pron-chip--good { background: #eaf8f1; border-color: #b8e6cf; color: #167c4a; }
.pron-chip--ok   { background: #fff8e0; border-color: #f2dd97; color: #8a6d10; }
.pron-chip--bad  { background: #fff1f1; border-color: #f3b9b9; color: #b42318; }
.pron-chip--na   { background: #f2f4f7; border-color: #e4e7ec; color: #98a2b3; }
</style>
