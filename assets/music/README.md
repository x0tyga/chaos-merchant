# Background Music

Drop royalty-free music tracks in this folder (`.mp3`, `.wav`, `.m4a`,
`.aac`, `.ogg`, `.flac`). The video production pipeline uses them as the
background music bed under the voiceover:

- The source video's own audio is **always stripped completely** - the
  final audio mix is voiceover + one track from this folder, nothing else.
- Track selection rotates per short (short 1 gets the first track
  alphabetically, short 2 the second, and so on, wrapping around), so a
  batch gets variety and a re-run picks the same tracks.
- Tracks shorter than a clip are looped; longer ones are trimmed.
- If this folder is empty, shorts are produced with voiceover-only audio -
  the pipeline never fails because of missing music.

Use music you have the rights to publish (YouTube Audio Library is a good
free source). Override this folder's location with `BACKGROUND_MUSIC_DIR`
in `.env`.
