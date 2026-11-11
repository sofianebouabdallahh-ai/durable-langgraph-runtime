"""Memory across chats (phase H8): the notes an agent keeps for the person, scoped by the
run row, validated before they're kept, in every turn's prompt, and theirs to see and
remove. `store` reads and writes, `rules` says what may be kept, `prompt` what the model
is shown."""
