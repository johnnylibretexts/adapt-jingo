<template>
  <div class="pron-embed p-2">
    <pronunciation-question
      v-if="exerciseId"
      :prompt="prompt"
      :exercise-id="exerciseId"
      :language="language"
      :service-url="serviceUrl"
      :tts-url="ttsUrl"
      mode="practice"
    />
    <p v-else class="text-danger">Missing exercise.</p>
  </div>
</template>

<script>
import PronunciationQuestion from '~/components/questions/PronunciationQuestion.vue'

export default {
  components: { PronunciationQuestion },
  layout: 'blank',            // bare layout, no navbar/login chrome
  computed: {
    exerciseId() { return this.$route.query.exercise_id || '' },
    language() { return this.$route.query.lang || 'es' },
    prompt() { return this.$route.query.prompt || '' },
    serviceUrl() { return window.config.pronunciationServiceUrl },
    ttsUrl() { return window.config.pronunciationTtsUrl },
  },
  // When embedded in an iframe (e.g. the mirror's book pages), report our own
  // content height to the parent so it can size the frame to fit — no inner
  // scrollbar. Harmless when not framed (postMessage to self, no listener).
  mounted() {
    // ADAPT injects a global "Support Center" widget (#support-widget-container)
    // at the page root. It's irrelevant chrome for a login-free practice embed
    // and, being position:fixed, clips at the iframe's edge — hide it. A style
    // rule (vs a one-shot removal) also covers the case where it mounts late.
    const s = document.createElement('style')
    s.textContent = '#support-widget-container{display:none!important}'
    document.head.appendChild(s)
    this.reportHeight = () => {
      try {
        const h = Math.ceil(this.$el.getBoundingClientRect().height) + 12
        window.parent.postMessage({ type: 'pron-embed-height', height: h }, '*')
      } catch (e) { /* postMessage to a cross-origin parent still succeeds */ }
    }
    this.reportHeight()
    window.addEventListener('load', this.reportHeight)
    if (window.ResizeObserver) {
      this.ro = new ResizeObserver(this.reportHeight)
      this.ro.observe(this.$el)
    } else {
      this.heightPoll = setInterval(this.reportHeight, 500)
    }
  },
  beforeDestroy() {
    window.removeEventListener('load', this.reportHeight)
    if (this.ro) this.ro.disconnect()
    if (this.heightPoll) clearInterval(this.heightPoll)
  },
}
</script>
