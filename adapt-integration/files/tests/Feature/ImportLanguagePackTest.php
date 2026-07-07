<?php

namespace Tests\Feature;

use App\Course;
use App\Assignment;
use App\AssignmentGroup;
use App\Question;
use Tests\TestCase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\File;

class ImportLanguagePackTest extends TestCase
{
    private $packPath;

    public function setUp(): void
    {
        parent::setUp();
        $this->user = factory(\App\User::class)->create(['role' => 2]);
        $this->recordsDir = sys_get_temp_dir() . '/pron-records-' . uniqid();
        File::ensureDirectoryExists($this->recordsDir);
        // tiny pack: 1 unit, 1 lesson, 1 pronunciation drill + 1 qti-mc
        $this->packPath = tempnam(sys_get_temp_dir(), 'pack') . '.json';
        file_put_contents($this->packPath, json_encode([
            'manifest' => ['course_title' => 'Spanish 1 Test', 'language' => 'es', 'version' => '1.0.0'],
            'course_code' => 'SPAN-1-TEST',
            'units' => [[
                'id' => 'es-u1', 'title' => 'Sonidos', 'order' => 1,
                'lessons' => [[
                    'id' => 'es-u1-l1', 'title' => 'Vocales', 'order' => 1,
                    'drills' => [
                        ['id' => 'es-u1-l1-e1', 'type' => 'pronunciation',
                         'prompt' => 'Pronounce: ala', 'target_text' => 'ala',
                         'grading' => 'completion',
                         'phonetics_record' => ['lang' => 'es', 'phones' => ['a','l','a'],
                            'ids' => [5,31,5], 'words' => [['start'=>0,'len'=>3,'phones'=>['a','l','a']]],
                            'coverage' => 1.0, 'unknown' => []]],
                        ['id' => 'es-u1-l1-q1', 'type' => 'qti-mc',
                         'prompt' => "¿Cómo se dice 'hello'?",
                         'qti_spec' => ['type' => 'multiple_choice',
                            'prompt' => "¿Cómo se dice 'hello'?",
                            'choices' => [['hola', true], ['adiós', false]]]],
                    ],
                ]],
                'exam' => ['title' => 'Examen U1', 'questions' => [
                    ['exercise_id' => 'es-u1-l1-e1', 'grading' => 'score', 'points' => 5],
                    ['exercise_id' => 'es-u1-l1-q1', 'points' => 3],
                ]],
            ]],
        ]));
    }

    public function tearDown(): void
    {
        File::deleteDirectory($this->recordsDir);
        @unlink($this->packPath);
        parent::tearDown();
    }

    /** @test */
    public function command_creates_course_assignments_questions_and_records()
    {
        $exit = \Artisan::call('libretexts:import-language-pack', [
            'file' => $this->packPath,
            '--user' => $this->user->id,
            '--records-dir' => $this->recordsDir,
        ]);
        $this->assertEquals(0, $exit, \Artisan::output());

        // NOTE: live `courses` table uses `name` (not `course_name`) — see
        // SeedDemo::ensureCourse (line 224). Adjusted per the brief's Step 4 note.
        $course = Course::where('name', 'Spanish 1 Test')->first();
        $this->assertNotNull($course);
        $lessonAssignment = Assignment::where('course_id', $course->id)
            ->where('name', 'like', '%Vocales%')->first();
        $this->assertNotNull($lessonAssignment);
        $exam = Assignment::where('course_id', $course->id)->where('name', 'Examen U1')->first();
        $this->assertNotNull($exam);
        $this->assertEquals('real time', $lessonAssignment->assessment_type);
        $this->assertEquals('delayed', $exam->assessment_type);

        $pronQ = Question::where('technology', 'pronunciation')
            ->where('technology_id', 'es-u1-l1-e1')->first();
        $this->assertNotNull($pronQ);
        $this->assertEquals('es', json_decode($pronQ->pronunciation_data, true)['language']);
        $this->assertEquals('completion', json_decode($pronQ->pronunciation_data, true)['grading']);

        // record written to records dir
        $this->assertFileExists($this->recordsDir . '/es/es-u1-l1-e1.json');
        // qti question created
        $qtiQ = Question::where('technology', 'qti')
            ->where('technology_id', 'es-u1-l1-q1')->first();
        $this->assertNotNull($qtiQ);

        // exam attached both (one pronunciation grading overridden to 'score')
        $examQids = DB::table('assignment_question')->where('assignment_id', $exam->id)->pluck('question_id');
        $this->assertContains($pronQ->id, $examQids->all());
        $this->assertContains($qtiQ->id, $examQids->all());
    }
}