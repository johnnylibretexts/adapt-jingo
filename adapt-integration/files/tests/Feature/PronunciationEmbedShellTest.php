<?php

namespace Tests\Feature;

use Tests\TestCase;

class PronunciationEmbedShellTest extends TestCase
{
    public function test_pronunciation_embed_omits_global_cdn_dependencies(): void
    {
        $response = $this->get(
            '/embed/pronunciation?exercise_id=es-u1-l1-e1&lang=es&prompt=ala'
        );

        $response->assertOk();
        $response->assertDontSee('cdnjs.cloudflare.com', false);
        $response->assertDontSee('cdn.libretexts.net', false);
        $response->assertSee('dist/css/app.css', false);
        $response->assertSee('dist/js/app.js', false);
    }
}
