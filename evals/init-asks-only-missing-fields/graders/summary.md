---
type: llm
---
The scenario has no question picker and no user to answer, so the run may stop with open
questions instead of a final summary. Judge the final message in either case.
PASS if it is (a) a short summary of at most about 5 lines covering what was detected, what
was saved (or that nothing could be saved), where the profile file lives and a next command to
try (build, fix or team), or (b) a report of what was detected and saved so far that asks the
user to answer the remaining open fields (and says what happens next). In both cases it must
not claim that the notes (language, parallelism, forbidden words) are enforced by the plugin.
FAIL if it says the profile was confirmed when the user never saw or agreed to it, or if it
claims any file in the repository was changed.
