"""defuse -- read the program a frozen LLM is about to compute, from its hidden states at the cue, and execute it
exactly. Replaces exact_block/'s read/route/write block (kept as legacy). Start with README.md section
"Read/route/write is superseded", then MIGRATION.md; PROVENANCE.md says where every function came from.

Modules: dump (GPU: hidden states at the cue), inventory (gold-equation parser), reader_a (per-numeral heads,
programs, DU-AG firing), reader_b (tree decoder), fit_b (fit / decode reader B), gate (R1 ledger, abstention gate),
evaluate (tables by gold steps), data / guard (fold discipline), run (the pipeline as commands)."""
