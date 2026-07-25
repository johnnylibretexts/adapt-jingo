<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

class AddPronunciationToQuestions extends Migration
{
    public function up(): void
    {
        // Extend the technology ENUM to include 'pronunciation'. Preserve the
        // values the live DB already accepts (h5p/webwork/imathas/qti/text).
        DB::statement(
            "ALTER TABLE questions CHANGE technology technology "
            . "ENUM('h5p','webwork','imathas','qti','text','pronunciation') DEFAULT NULL"
        );

        Schema::table('questions', function (\Illuminate\Database\Schema\Blueprint $table) {
            $table->json('pronunciation_data')->nullable()->after('technology');
        });
    }

    public function down(): void
    {
        Schema::table('questions', function (\Illuminate\Database\Schema\Blueprint $table) {
            $table->dropColumn('pronunciation_data');
        });
        // Restore the pre-migration type (VARCHAR(15) per
        // migration 2020_09_10_141644). up() locked it to
        // ENUM(6); rollback undoes that lockdown.
        DB::statement(
            "ALTER TABLE questions CHANGE technology technology "
            . "VARCHAR(15) DEFAULT NULL"
        );
    }
}