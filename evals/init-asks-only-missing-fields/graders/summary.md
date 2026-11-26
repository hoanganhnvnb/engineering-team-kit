---
type: llm
---
The final message ends with a short summary of at most about 5 lines that says (1) what was
detected, (2) what was saved or that nothing could be saved, (3) where the profile file lives,
and (4) a next command to try (build, fix or team). PASS only if all four are present and the
message does not claim that the notes (language, parallelism, forbidden words) are enforced by
the plugin. FAIL if it says the profile was confirmed when the user never saw or agreed to it,
or if it claims any file in the repository was changed.
