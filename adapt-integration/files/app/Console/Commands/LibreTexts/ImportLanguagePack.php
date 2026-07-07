<?php

namespace App\Console\Commands\LibreTexts;

use App\Assignment;
use App\AssignmentGroup;
use App\Course;
use App\Question;
use App\Section;
use App\Console\Commands\LibreTexts\SeedDemo;   // for buildQtiJson()
use Illuminate\Console\Command;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\File;

/**
 * Import an offline language content pack into ADAPT.
 *
 * Creates the course graph (course -> assignment_groups -> assignments ->
 * questions) from a pack JSON and writes phonetics reference records to a
 * directory the pron service reads (no G2P at runtime — G2P is build-time in
 * Task 11; the runtime pron service reads these records with no espeak).
 *
 * Idempotent: re-running with the same pack/user updates in place via
 * firstOrNew/updateOrInsert. Patterned on libretexts:seed-demo (SeedDemo).
 *
 * Column names verified against SeedDemo::ensureCourse/ensureAssignment and
 * the live migrations (see the brief's Step 4 note): courses.name (not
 * course_name), courses.alpha is boolean, assignments has no user_id column,
 * assessment_type is varchar(15) with values 'real time'/'delayed'/'learning
 * tree' (per migration 2020_12_18_182538 + SeedDemo::assignmentSpec), and the
 * folder table is saved_questions_folders (user_id/name/type) — there is no
 * `folders` table.
 *
 * Hybrid grading: questions.pronunciation_data.grading stores the DRILL's
 * grading ('completion' by default). The per-exam 'score' override declared
 * in the pack's exam section is honored by the runtime pron service from the
 * pack context — it is NOT mutated onto the shared question row here, so a
 * question used in both a lesson (completion) and an exam (score) keeps its
 * drill-default grading on the question and is graded per-context at runtime.
 *
 * No clinical/academic validity or channel-independent threshold is claimed.
 * License: ccby/4.0 on imported questions. No TalkBank-derived data embedded.
 */
class ImportLanguagePack extends Command
{
    protected $signature = 'libretexts:import-language-pack
        {file : Path to the pack JSON}
        {--user= : Instructor user id to own the course}
        {--records-dir= : Directory to write phonetics records (default /opt/libretexts/pron/records)}';

    protected $description = 'Import an offline language content pack into ADAPT (course -> assignment_groups -> assignments -> questions).';

    public function handle(): int
    {
        $file = $this->argument('file');
        if (!file_exists($file)) {
            $this->error("Pack file not found: $file");
            return 1;
        }
        $pack = json_decode(file_get_contents($file), true);
        if (!$pack || empty($pack['units'])) {
            $this->error("Invalid pack: missing manifest/units.");
            return 1;
        }

        $userId = (int) $this->option('user');
        if (!$userId || !\App\User::find($userId)) {
            $this->error("--user <instructor id> is required and must exist.");
            return 1;
        }
        $recordsDir = $this->option('records-dir') ?: '/opt/libretexts/pron/records';
        File::ensureDirectoryExists($recordsDir);
        $lang = $pack['manifest']['language'] ?? 'es';

        DB::transaction(function () use ($pack, $userId, $recordsDir, $lang) {
            $course = $this->ensureCourse($pack, $userId);
            $folderId = $this->ensureFolder($course, $userId);

            // Per-course defaults that ADAPT's normal course-creation path
            // (CourseController::prepareNewCourse) sets up but which this command
            // otherwise skips. Without them the STUDENT scores endpoint 500s:
            //   - final_grades: ScoreController::getCourseScoresByUser reads
            //     $course->finalGrades->letter_grades_released (null -> fatal);
            //   - assignment_group_weights (below, per group): getAssignmentGroupWeights
            //     joins on it to build the assignment->group map; an empty map -> an
            //     undefined-key fatal in Score::getScoresByUserIdAndAssignment.
            // Section + enrollments make the course demo-ready for the seeded students.
            $this->ensureFinalGrades($course->id);
            $section = $this->ensureSection($course->id);
            $this->ensureDemoEnrollments($course->id, $section->id);

            foreach ($pack['units'] as $unit) {
                $group = $this->ensureAssignmentGroup($course->id, $userId, $unit['title']);
                // Every assignment group needs a weight row or the scores endpoint 500s (see above).
                $this->ensureAssignmentWeight($group->id, $course->id);
                foreach ($unit['lessons'] as $lesson) {
                    $assignment = $this->ensureAssignment(
                        $course->id, $userId, $group->id,
                        sprintf('U%d L%d — %s', $unit['order'], $lesson['order'], $lesson['title'])
                    );
                    $order = 1;
                    foreach ($lesson['drills'] as $drill) {
                        $question = $this->ensureQuestion($drill, $userId, $folderId, $lang);
                        if ($drill['type'] === 'pronunciation') {
                            $this->writeRecord($recordsDir, $lang, $drill);
                        }
                        $this->attachQuestion($assignment->id, $question->id, $order, $drill['points'] ?? 2);
                        $order++;
                    }
                }
                // exam (optional): attach existing questions with per-exam points.
                // The per-exam 'score' grading override declared in the pack is
                // honored by the runtime pron service from the pack context; it is
                // NOT mutated onto the shared question row (preserves hybrid grading
                // — a question used in a lesson keeps its drill-default grading).
                if (!empty($unit['exam'])) {
                    $exam = $this->ensureAssignment($course->id, $userId, $group->id, $unit['exam']['title'], true);
                    $order = 1;
                    foreach ($unit['exam']['questions'] as $eq) {
                        $question = Question::where('technology_id', $eq['exercise_id'])->first();
                        if (!$question) {
                            $this->warn("Exam references unknown exercise: {$eq['exercise_id']}");
                            continue;
                        }
                        $this->attachQuestion($exam->id, $question->id, $order, $eq['points'] ?? 2);
                        $order++;
                    }
                }
            }
        });

        $this->info("Imported pack: {$pack['manifest']['course_title']} → records at $recordsDir");
        return 0;
    }

    private function ensureCourse(array $pack, int $userId): Course
    {
        // courses.name (not course_name) — see SeedDemo::ensureCourse line 224.
        $course = Course::firstOrNew(['name' => $pack['manifest']['course_title']]);
        $course->user_id = $userId;
        $course->public_description = $pack['manifest']['summary'] ?? 'Imported from offline language pack.';
        $course->textbook_url = '';   // no book behind a language pack
        $course->term = 'Language Pack';
        // start_date/end_date are NOT NULL on courses (base migration).
        $course->start_date = Carbon::now()->copy()->subWeek();
        $course->end_date = Carbon::now()->copy()->addMonths(4);
        $course->order = 1;
        $course->public = 1;
        $course->lms = 0;
        $course->question_numbers_shown_in_iframe = 1;
        // courses.alpha is boolean (not a string course code) — SeedDemo line 237.
        $course->alpha = 0;
        $course->anonymous_users = 0;
        // school_id has a DB default ('Not Specified' school) — omit to use it.
        $course->shown = 1;
        $course->students_can_view_weighted_average = 1;
        if (!$course->exists) {
            $course->save();
        }
        return $course;
    }

    /**
     * Ensure a saved-questions folder named after the course for the instructor.
     * The table is `saved_questions_folders` (user_id/name/type) — there is NO
     * `folders` table and no `folder_name`/`course_id` columns on it. Mirrors
     * SeedDemo::ensureQuestionFolder (lines 200-211).
     */
    private function ensureFolder(Course $course, int $userId): int
    {
        DB::table('saved_questions_folders')->updateOrInsert(
            ['user_id' => $userId, 'name' => $course->name, 'type' => 'my_questions'],
            ['updated_at' => Carbon::now(), 'created_at' => Carbon::now()]
        );
        return (int) DB::table('saved_questions_folders')
            ->where('user_id', $userId)
            ->where('name', $course->name)
            ->where('type', 'my_questions')
            ->value('id');
    }

    private function ensureAssignmentGroup(int $courseId, int $userId, string $title): AssignmentGroup
    {
        // Matches SeedDemo::ensureAssignmentGroup (lines 277-286).
        $group = AssignmentGroup::firstOrNew([
            'course_id' => $courseId, 'user_id' => $userId, 'assignment_group' => $title,
        ]);
        if (!$group->exists) {
            $group->save();
        }
        return $group;
    }

    private function ensureFinalGrades(int $courseId): void
    {
        // Mirrors SeedDemo::ensureFinalGrades (lines 246-258).
        DB::table('final_grades')->updateOrInsert(
            ['course_id' => $courseId],
            [
                'letter_grades' => '90,A,80,B,70,C,60,D,0,F',
                'round_scores' => 0,
                'letter_grades_released' => 0,
                'updated_at' => Carbon::now(),
                'created_at' => Carbon::now(),
            ]
        );
    }

    private function ensureSection(int $courseId): Section
    {
        // Reuse the course's existing section if it already has one (an imported
        // course may have been given a section elsewhere) — only create otherwise.
        // Avoids duplicate sections on re-import and keeps enrollments consistent.
        $section = Section::where('course_id', $courseId)->first();
        if (!$section) {
            $section = new Section();
            $section->name = 'Sandbox Section';
            $section->course_id = $courseId;
            $section->crn = 'DEV-' . $courseId;
            $section->access_code = 'sandbox-' . $courseId;
            $section->save();
        }
        return $section;
    }

    private function ensureDemoEnrollments(int $courseId, int $sectionId): void
    {
        // Enroll the same demo students SeedDemo creates (real + fake), if present,
        // so an imported language course is immediately demo-ready for a student login.
        foreach (['student@libretexts.dev', 'fake.student@libretexts.dev'] as $email) {
            $student = \App\User::where('email', $email)->first();
            if ($student) {
                $this->ensureEnrollment($courseId, $sectionId, (int) $student->id);
            }
        }
    }

    private function ensureEnrollment(int $courseId, int $sectionId, int $userId): void
    {
        // The enrollments unique key is (user_id, course_id) — match on that so a
        // student already enrolled (possibly via another section) updates in place
        // instead of hitting a duplicate-key error. section_id is set/updated.
        DB::table('enrollments')->updateOrInsert(
            ['course_id' => $courseId, 'user_id' => $userId],
            ['section_id' => $sectionId, 'updated_at' => Carbon::now(), 'created_at' => Carbon::now()]
        );
    }

    private function ensureAssignmentWeight(int $assignmentGroupId, int $courseId): void
    {
        // Mirrors SeedDemo::ensureAssignmentWeight (lines 442-448).
        DB::table('assignment_group_weights')->updateOrInsert(
            ['assignment_group_id' => $assignmentGroupId, 'course_id' => $courseId],
            ['assignment_group_weight' => 100, 'updated_at' => Carbon::now(), 'created_at' => Carbon::now()]
        );
    }

    /**
     * Ensure an assignment. The `assignments` table has NO user_id column
     * (ownership flows via courses.user_id) — see SeedDemo::ensureAssignment
     * (lines 374-416) which never sets user_id. assessment_type is varchar(15)
     * with values 'real time'/'delayed'/'learning tree' (per migration
     * 2020_12_18_182538 + SeedDemo::assignmentSpec — homework/quiz='real time',
     * exam='delayed'). The full field set mirrors SeedDemo so the save
     * satisfies NOT NULL constraints (e.g. scoring_type, late_policy).
     * scoring_type='p' so per-question grading/points apply.
     */
    private function ensureAssignment(int $courseId, int $userId, int $groupId, string $name, bool $isExam = false): Assignment
    {
        $assignment = Assignment::firstOrNew(['course_id' => $courseId, 'name' => $name]);
        $now = Carbon::now();
        $assignment->public_description = 'Imported from offline language pack.';
        $assignment->formative = 0;
        $assignment->assessment_type = $isExam ? 'delayed' : 'real time';   // varchar(15): real time/delayed/learning tree (mirrors SeedDemo::assignmentSpec)
        $assignment->assignment_group_id = $groupId;
        $assignment->source = 'a';
        $assignment->instructions = 'Complete the pronunciation drills and comprehension items from the language pack.';
        $assignment->scoring_type = 'p';      // points-based
        $assignment->points_per_question = 'number of points';
        $assignment->default_points_per_question = 2;
        $assignment->total_points = 12;
        $assignment->show_points_per_question = 1;
        $assignment->file_upload_mode = 'text';
        $assignment->default_open_ended_submission_type = 'text';
        $assignment->default_open_ended_text_editor = 'rich';
        $assignment->late_policy = 'not accepted';
        $assignment->shown = 1;
        $assignment->show_scores = 1;
        $assignment->solutions_released = 1;
        $assignment->question_url_view = 'assignment';
        $assignment->graders_can_see_student_names = 1;
        $assignment->students_can_view_assignment_statistics = 1;
        $assignment->include_in_weighted_average = 1;
        $assignment->notifications = 0;
        $assignment->textbook_url = '';
        // submission_files was dropped from assignments by migration
        // 2021_01_07_132829 (along with submission_texts) — do not set it.
        $assignment->order = 1;
        $assignment->created_at = $assignment->created_at ?: $now;
        $assignment->updated_at = $now;
        if (!$assignment->exists) {
            $assignment->save();
        }
        return $assignment;
    }

    /**
     * Ensure a question for a drill. Mirrors SeedDemo::ensureQtiQuestion's field
     * set (lines 558-599) for the common fields; the pronunciation branch adds
     * technology='pronunciation' (Task 6 migration) + pronunciation_data JSON,
     * the qti branch reuses SeedDemo::buildQtiJson() verbatim.
     */
    private function ensureQuestion(array $drill, int $userId, int $folderId, string $lang): Question
    {
        $sourceUrl = "demo://pron/{$userId}/" . md5($drill['id']);
        $question = Question::firstOrNew([
            'technology_id' => $drill['id'], 'source_url' => $sourceUrl,
        ]);
        $question->question_type = 'assessment';
        $question->page_id = 940000000 + (crc32($sourceUrl) % 10000000);
        $question->library = 'adapt';
        $question->url = $sourceUrl;
        $question->title = $drill['prompt'];
        $question->technology_iframe = '';
        $question->non_technology = 0;
        $question->non_technology_html = '';
        $question->text_question = strip_tags($drill['prompt']);
        $question->answer_html = '<p>Pronunciation drill.</p>';
        $question->solution_html = '<p>Listen to the model and repeat.</p>';
        $question->hint = $drill['target_text'] ?? '';
        $question->libretexts_link = $sourceUrl;
        $question->notes = 'Imported pronunciation drill.';
        $question->auto_attribution = 1;
        $question->author = 'LibreTexts Language Pack';
        $question->question_editor_user_id = $userId;
        $question->license = 'ccby';
        $question->license_version = '4.0';
        $question->source_url = $sourceUrl;
        $question->attribution = 'Imported from offline language pack.';
        $question->public = 1;
        $question->cached = 1;
        $question->version = 1;
        $question->folder_id = $folderId;

        if ($drill['type'] === 'pronunciation') {
            $question->technology = 'pronunciation';
            $question->pronunciation_data = json_encode([
                'exercise_id' => $drill['id'],
                'language' => $lang,
                'grading' => $drill['grading'] ?? 'completion',
            ]);
        } elseif ($drill['type'] === 'qti-mc' || $drill['type'] === 'qti-fill') {
            $spec = $drill['qti_spec'];
            $question->technology = 'qti';
            $question->qti_json = SeedDemo::buildQtiJson($spec['type'], $spec);
            $question->qti_json_type = $spec['type'];
        } else {
            throw new \InvalidArgumentException("Unknown drill type: {$drill['type']}");
        }
        $question->save();
        // belt-and-suspenders raw update for the technology ENUM (mirrors
        // SeedDemo::ensureLocalQuestion line 497 — the model save alone can be
        // unreliable for the technology ENUM column).
        DB::table('questions')->where('id', $question->id)->update(['technology' => $question->technology]);
        return $question;
    }

    /**
     * Write the phonetics reference record (phones/ids/words/coverage) verbatim
     * to <records-dir>/<lang>/<exercise_id>.json. No G2P at runtime — the record
     * is pre-built (Task 11) and the runtime pron service reads it with no
     * espeak. Also writes a per-language tag_map if provided on the drill.
     */
    private function writeRecord(string $recordsDir, string $lang, array $drill): void
    {
        $dir = "$recordsDir/$lang";
        File::ensureDirectoryExists($dir);
        file_put_contents("$dir/{$drill['id']}.json", json_encode($drill['phonetics_record']));
        if (!empty($drill['tag_map']) && !file_exists("$recordsDir/tag_map/$lang.json")) {
            File::ensureDirectoryExists("$recordsDir/tag_map");
            file_put_contents("$recordsDir/tag_map/$lang.json", json_encode([
                'language' => $lang, 'map' => $drill['tag_map'], 'unmapped_neutral' => [],
            ]));
        }
    }

    /**
     * Attach a question to an assignment via the assignment_question pivot.
     * Points are taken from the pack (default 2). open_ended_submission_type='0'
     * (auto-graded, not open-ended) — matches SeedDemo::attachQuestion's
     * auto-graded path (lines 746-765).
     */
    private function attachQuestion(int $assignmentId, int $questionId, int $order, float $points): void
    {
        DB::table('assignment_question')->updateOrInsert(
            ['assignment_id' => $assignmentId, 'question_id' => $questionId],
            [
                'open_ended_submission_type' => '0',   // auto-graded (not open-ended)
                'open_ended_text_editor' => null,
                'open_ended_default_text' => null,
                'points' => (int) $points,             // column is unsignedTinyInteger
                'weight' => null,
                'completion_scoring_mode' => null,
                'assignment_information_shown_in_iframe' => 1,
                'submission_information_shown_in_iframe' => 1,
                'attribution_information_shown_in_iframe' => 1,
                'order' => $order,
                'updated_at' => Carbon::now(), 'created_at' => Carbon::now(),
            ]
        );
    }
}