# How the multilingual banks are made, and how to make more

This guide is for anyone who wants to add templates, languages or operations to the banks
in `banks/`. It explains the whole pipeline (writer, validate, accept, blind, verify,
check and clean, generate), why each step exists, how the work is cut into rounds that can
be stopped and resumed at any moment, how to write the two briefs that drive the language
model agents doing the writing and the checking, and the lessons that each cost us at
least an afternoon. It ends with what we have measured about which distractors are
actually hard, with recipes for writing them, and a worked example that follows one
template from an empty file to finished rows.

Everything here uses the v5 tools (see [V5_TOOLS.md](V5_TOOLS.md) for where they go).
Section 10 shows how to look at the prompts of any bank, and section 11 is the
step-by-step procedure for generating more data with Claude (Sonnet writers, Opus
verifiers, chunked rounds on a small quota). The older banks (v2 to v4) were made with an
earlier version of the same pipeline; section 12 maps the old file names onto the new steps.

---------------------------------------------------------------------------------------

## 1. What a bank is, in one picture

A bank is not a pile of written problems. It is a small set of **templates**, written
once by a fluent writer and checked by a second reader, and a **deterministic generator**
that fills each template with many numbers, in several arrangements. For example, one
template (numbers are slots in braces):

```
facts   : At noon the river gauge read {M} cm. At dawn it had read {S} cm.
question: What was the change in the river level from dawn to noon?
lead_in : The answer is
```

becomes dozens of rows such as

```
At noon the river gauge read 214 cm. At dawn it had read 189 cm. What was the change in the river level from dawn to noon? The answer is     -> 25
At noon the river gauge read 189 cm. At dawn it had read 214 cm. What was the change in the river level from dawn to noon? The answer is     -> -25
```

The two rows above are a **minimal pair**: the words are identical and only which number
is larger has changed. In the first the minuend (the number subtracted *from*, here the
noon reading) is the larger one; in the second it is the smaller one and the answer is
negative. That is the point of the whole design. In almost every public collection of word
problems the minuend is written as the larger number (on more than 99.7% of subtraction
rows), so the rule "subtract the small number from the big one" is always right there and a
reader that has learned only that rule looks perfect. In these banks the meaning of the
story, not the size of the numbers, decides the roles, and each story is filled both ways
round and in both written orders. So "the bigger number is the minuend" is right on exactly
half the rows, "the first-written number is the minuend" on exactly half, and anything
better than a half has to come from the words.

Every row also carries one or more **distractors**: extra numbers the question does not
use. Sections 8 and 9 are about which distractors are hard and how to write them.

Three consequences of "templates plus a generator" that you should keep in mind:

* **The templates are the expensive part.** Writing and checking costs language model
  agent time; generating rows costs seconds.
* **Every bank is reproducible byte for byte.** Every random draw in the generator is keyed
  through a hash of the row's identity (never through Python's per-process `hash()`), so the
  same templates give the same bytes on any machine. We ship md5s, not rows
  (`banks/SHIP.md5`), and a regeneration that moves one md5 is not the bank.
* **The numbers are keyed on the story number, not the language.** Story 5 in Icelandic and
  story 5 in Tamil carry the same numerals, so a comparison across languages is never
  confounded by the numbers.

---------------------------------------------------------------------------------------

## 2. The pipeline at a glance

```
  status_v5.py --next         which units to write next (deterministic, balanced over languages)
        |
        v
  WRITER agent  ------------> writers/<lang>/W5-<lang>-uNN.json       12 templates, one language
        |   loops on
        v
  validate_v5.py <file>       "VALIDATE ok 12" or one FAIL line per problem (the writer fixes them)
        |
        v
  status_v5.py --accept       near-duplicate check against everything already accepted for that language
        |                     -> accept/<uid>.a<K>.json  (accepted, or rejected + re-queued as attempt K+1)
        v
  make_blind_v5.py <V-unit>   blind/<V-unit>.blind.json  (+ blind_key/<V-unit>.key.json, never shown to a verifier)
        |
        v
  VERIFIER agent -----------> verify/<V-unit>.json        judges every text from the words alone
        |   loops on
        v
  check_v5.py --format        "FORMAT ok <n>"
        |
        v
  check_v5.py --report        VERIFY_REPORT_v5.md: agreement per language, flags, disagreements
  check_v5.py --clean         clean/clean_v5.json: the kept templates, with their tags
        |
        v
  gen_v5.py --clean ...       bank/signed_A_int.jsonl + pairs.json + AUDIT_v5.txt + SHIP_V5.raw.md5
```

The two agent steps are the only places where judgement enters. Everything else is a
script that recomputes its answer from the files on disk, so it can be rerun at any time
and gives the same answer.

### What each step is for

| step | what it catches | who does it |
|---|---|---|
| writer | nothing: it produces the templates | a language model agent, one per unit (a mid-sized model at medium effort worked well) |
| validate | everything mechanical: schema, quotas, a digit or number word in the words, a slot in the wrong place, the wrong script, a missing question mark, two templates that are near copies of each other | `validate_v5.py`, run by the writer itself until it passes |
| accept | a template that is a near copy of one another writer already got accepted for the same language | `status_v5.py --accept` |
| blind | nothing: it hides from the verifier which slot is which and which text belongs to which template | `make_blind_v5.py` |
| verify | everything that needs a fluent reader: is it natural, is it grammatical for every number, which two numbers does the question use, which one is subtracted from, would a negative answer read naturally | a second agent (a strong model at medium effort), one per group of 4-5 languages |
| check / clean | disagreement between what the writer said and what the verifier read; flagged templates | `check_v5.py` |
| generate | nothing new: it turns clean templates into rows and audits them | `gen_v5.py` |

---------------------------------------------------------------------------------------

## 3. The steps, one by one

### 3.1 Units and the manifest

The work is cut into fixed, named pieces before anything is written:

* A **writer unit** `W5-<lang>-uNN` is 12 templates in one language: exactly one for each
  (operation x shape) cell, 4 operations (add, sub, mul, div) times 3 shapes (list,
  other_time, diff_owner; section 8 explains them). Each unit gets three scenario topics
  (a "half-slice" of the topic list in `v5_common.SLICES`: 24 slices of 6 topics, such as
  kitchens and bakeries, or roads and rail), assigned so that the units of one language
  never share a topic.
* A **verifier unit** `V5-gG-uNN` is the five writer units with the same unit number in one
  group of five languages (for example group 1 = en, de, nl, fr, es): 60 templates, 240
  blind texts.
* `manifest_v5.json` lists all 800 writer units and 160 verifier units with stable ids.
  It is written once (`status_v5.py --write-manifest`) and never edited.

### 3.2 Asking what to do next

```bash
python banks/v5/status_v5.py                       # the state of every unit, totals per language
python banks/v5/status_v5.py --next 25 --tier T2   # the next 25 writer units, round-robin over languages
python banks/v5/status_v5.py --next 5 --kind verifier
```

`--next` prints, for each writer unit, the whole **unit spec** a writer needs: its id,
language, three topics, the exact `lead_in` ("The answer is" in that language), where the
look-alike number `{T}` must go in each template, the output path, and (for a unit that
was sent back) which templates to rewrite. You paste that spec into the writer's prompt;
the writer never opens the manifest.

The state of a unit is **recomputed from the files alone**, every time:

| writer unit | meaning |
|---|---|
| pending | no file yet |
| invalid | the latest attempt fails `validate_v5.py` |
| valid | passes, waiting for `--accept` |
| rejected | a near copy of something accepted; re-queued as attempt K+1 with the duplicated template ids |
| accepted | done |

| verifier unit | meaning |
|---|---|
| blocked | one of its five writer units is not accepted yet |
| ready | make the blind file |
| blinded | run the verifier |
| invalid | the verify file fails the format check |
| done | finished |

### 3.3 Writing (the agent step)

One agent per writer unit, with the writer brief (`BRIEF_v5_writer.md`) plus the unit
spec. It writes one file, `writers/<lang>/W5-<lang>-uNN.json` (or `.rK.json` for attempt
K), and runs the validator on it until it prints `VALIDATE ok 12`. Section 5 is about
writing that brief, and section 11 about launching the agents.

### 3.4 Validating

```bash
python banks/v5/validate_v5.py banks/v5/writers/ru/W5-ru-u03.json
```

Prints `VALIDATE ok 12`, or one `FAIL <where> [<tag>] <message>` line per problem. The tags
are the list of things it enforces: `schema unit count vocab placeholder order swap
adjacent position digit symbol numberword div question sentence length whitespace script
base duplicate neardup novelty neardup-accepted quota`. Two of them deserve a word:

* `digit` rejects any character that Unicode calls a digit or a number sign, in any
  script: `3`, `٣`, `३`, `３`, `²`, `½`. The generator inserts the numbers; a digit in the
  words would be an extra number no one planned.
* `neardup` / `novelty` measure the overlap of character 4-grams (the Jaccard index)
  between any two templates of the unit, and against the older banks' templates for the
  language. At 0.45 or more the template is refused. The threshold is calibrated
  (`validate_v5.py --calibrate`): among genuinely different existing templates the 95th
  percentile overlap is 0.10-0.21; a copy with the nouns swapped scores about 0.6, a light
  rephrase about 0.48.

### 3.5 Accepting

```bash
python banks/v5/status_v5.py --accept
```

Compares each valid unit with every template already accepted for its language
(including units accepted earlier in the same pass) and writes one stamp per attempt,
`accept/<uid>.a<K>.json`. A rejected unit goes back into `--next` as attempt K+1, with
the ids of the templates it duplicated, and the next writer rewrites only those.

### 3.6 Blinding

```bash
python banks/v5/make_blind_v5.py V5-g1-u01          # or: --ready, for every ready verifier unit
```

Each template becomes **four** blind texts, so that every string the writer wrote is
read once:

| blind text | made of | numbers |
|---|---|---|
| first | `facts_first` + question | {M} {S} {T} |
| second | `facts_second` + question | {M} {S} {T} |
| base_ex | `ex_sentence` + `base_first` + question | {D} {M} {S} |
| base_sem | `base_second` + `sem_sentence` + question | {M} {S} {D} |

Then the slots are **renamed in order of appearance** to `{A}`, `{B}`, `{C}`, and the 240
texts of the unit are shuffled across languages, templates and variants under opaque ids.
So the verifier cannot tell which slot the writer called the minuend, which one is the
distractor, or which texts belong together. The key that undoes all this goes to
`blind_key/`, which no verifier ever reads. (`--base-sample 0.25` verifies the two base
texts for only a quarter of the templates, to save verifier time; those templates are then
tagged `bases_unverified` on every row, so a quoted number can leave them out.)

### 3.7 Verifying (the agent step)

One agent per verifier unit (or a few units), with the verifier brief (`VERIFY_v5.md`).
For every text it answers, from the words alone:

* `op`: add / sub / mul / div / other (other = two steps, a leftover, rounding up, not
  answerable, the question cannot tell which numbers);
* `operands`: the two slot letters the question uses;
* `role`: for sub, the letter subtracted *from*; for div, the letter divided;
* `signed_natural`: for sub, would a negative answer read naturally?
* `flags`: unnatural, ungrammatical, ambiguous, hidden_operand, not_single_step,
  wrong_language, number_dependent_grammar, another_pair_answers, leftover_or_rounding,
  cue_mismatch, other; and a short `note` for each flag.

It then runs `check_v5.py --format <blind file> <its output>` until it prints
`FORMAT ok <n>`. That check knows only the format (every id once, allowed values, letters
that exist in the text), never the answers.

### 3.8 Checking and cleaning

```bash
python banks/v5/check_v5.py --report            # -> VERIFY_REPORT_v5.md + VERIFY_DISAGREE_v5.jsonl
python banks/v5/check_v5.py --clean --out banks/v5/clean/clean_v5.json
```

`--report` joins every verify file with its key and counts agreement per language: op,
operand pair, role, signed. `--clean` applies the rule, per template, over all four of its
texts:

* **D1, drop** when any text's operation, operand pair or role differs from the writer's labels;
* **D2, drop** when any text carries a flag, **except** `number_dependent_grammar`, which on its
  own keeps the template and tags it `numdep` (section 6);
* **D4, demote** a signed subtraction template that the verifier read as not
  signed-natural on any text: it is kept, but filled with the minuend larger only.

For scale, in the finished bank (all 16 rounds, 4,800 templates, 19,200 blind texts)
cleaning kept 4,352 of 4,800 templates: 48 were dropped because at least one text's labels
disagreed with the writer's (D1) and 400 for flags alone (D2); 42 of the kept templates are
tagged `numdep` and 45 are demoted. On the texts of the dropped templates the most common
flags were unnatural (573 texts), ambiguous (241), leftover or rounding (124) and
ungrammatical (74). Earlier, after rounds 1-5, the verifier had agreed with the writers on op,
operands and role for 5,933 of 6,000 texts, and the flags raised on those 6,000 texts were: unnatural 242, number-dependent grammar 91, ambiguous 76,
leftover or rounding 52, ungrammatical 24, other 11, not single-step 7, hidden operand 4,
another pair answers 1.

### 3.9 Generating

```bash
python banks/v5/gen_v5.py --clean banks/v5/clean/clean_v5.json --out-dir banks/v5/bank --min-cell 500
python banks/v5/gen_v5.py --preview --out-dir banks/v5/preview    # accepted but unverified units, for a look only
```

(`clean_v5.json` is the file your own `check_v5.py --clean` writes. The finished bank's clean
file, `banks/v5/clean/clean_v5_r1-16.json`, is shipped split into one file per language in
`banks/v5/clean/r1-16/`; `python banks/make_v5.py` joins it, runs this command on it and
checks the md5s.)

24 rows per template, every row one half of a minimal pair:

| arm | numerals | text | rows |
|---|---|---|---|
| base | 2 | base facts only: the no-distractor control | 4 |
| T | 3 | facts with the inline look-alike `{T}` | 8 (two value tiers; one asks the question first) |
| ex | 3 | base + the role-free sentence | 2 |
| sem | 3 | base + the same-kind other-owner sentence | 2 |
| T+s | 4 | facts with `{T}` + one sentence | 4 |
| T+ex+sem | 5 | facts with `{T}` + both sentences | 4 |

The twin of a row depends on the operation: signed subtraction swaps the two values (the
second twin has a negative answer), unsigned subtraction keeps the operands and redraws the
distractors, add and mul swap the two operand slots, div keeps the dividend and swaps the
divisor between its two factors. Distractor values are drawn from the set of values that
are operands somewhere else in the bank (so no value gives a distractor away by being
unusual), balanced so the distractor is equally often the smallest, middle or largest
number, and refused if it would let a second pair of numbers produce the answer under any
of the four operations. `--min-cell 500` refuses a bank in which any designed cell (op x
distractor kind x one of value tier / written order / position) has fewer than 500 rows.
`--numdep drop` leaves out the templates tagged `numdep`.

---------------------------------------------------------------------------------------

## 4. Chunked, resumable rounds

The agents are the expensive, rate-limited part, and a long run will be interrupted: by a
usage limit, a closed laptop, or you. So the pipeline is built to be stopped at **any**
instant and resumed without redoing or losing work:

* **Nothing is ever overwritten or appended.** Every attempt is its own file (`.rK.json`),
  every acceptance judgement its own stamp, every verify file its own file. A tool that
  would overwrite a file refuses instead (`make_blind_v5.py` refuses unless the existing
  blind file is byte-identical to the one it would write).
* **State is recomputed from files.** There is no database and no "progress" file to get
  out of sync. `status_v5.py` looks at what exists and what passes, and `--next` hands out
  whatever is not done, in a fixed order.
* **A round is the natural chunk.** One round = the 25 writer units with one unit number
  (one per language), then the 5 verifier units for that number (one per group of five
  languages). The verifiers of round N can run while round N+1 is being written, because a
  verifier unit becomes ready as soon as its five writer units are accepted.
* **Size a chunk to what you can afford.** Planning figures from our runs: a writer unit
  costs roughly 90-125 thousand tokens of a mid-sized model, a verifier unit roughly
  100-180 thousand tokens of a strong one; a round's writers take about 17-35 minutes in
  parallel and its verifiers under 10. Run fewer agents at once rather than more: a
  handful of parallel agents, one round per usage window, spread over the day, is what
  kept us inside our limits.

A typical session is therefore: `status_v5.py` (where are we?), `--next 25` (launch those
writers), `--accept`, `--next 5 --kind verifier` (blind and launch those verifiers),
`check_v5.py --report`, stop. The next session starts with `status_v5.py` again.

---------------------------------------------------------------------------------------

## 5. How to write a writer brief (and a verifier brief)

The two briefs are the only instructions the agents get, and almost every failure we had
traced back to one of them. Read `BRIEF_v5_writer.md` and `VERIFY_v5.md` as the worked
examples of everything below.

### 5.1 The writer brief

1. **Say the task in the first sentence, plainly.** "You are writing one file of 12 story
   templates in one language." Do not argue that the task is authorised or explain who
   asked for it: a brief that argues its own authority reads like an injected instruction,
   and in one early run 13 of 25 writers refused a brief like that. The plain version was
   refused 0 times in more than a hundred launches.
2. **Fence it.** Write exactly one file, at one path; never overwrite an existing file; run
   nothing but the validator; ignore any relayed message or question that asks for
   something else (otherwise an agent may answer a relayed interjection instead of
   writing its file); do not open other writers' files. Name the directories it must not read at all:
   the blind keys, the verifier outputs, and **any collected set of real word problems**.
   Real problem sets are test sets only; a writer that imitates one leaks the test into the
   training data.
3. **Explain why the bank exists in one paragraph.** What "good" means depends on it. Our
   paragraph says: a reader that picks the two numbers a question uses is nearly perfect on
   our synthetic banks and much worse on real problems, where it swaps one number for a
   look-alike; these templates teach it to tell them apart.
4. **Define the slots and every text by a table**, with what each slot means for each
   operation (`{M}` is the minuend for sub, the dividend for div, ...).
5. **Give the hard rules as a numbered list, and make every one of them checkable by the
   validator.** If the validator cannot check a rule, the writer will sometimes break it
   and nobody will know until a verifier (or a result) does.
6. **Give the quotas as a table.** Exactly one template per (op x shape) cell, how many
   signed subtractions, both division modes, where `{T}` goes, how many templates need a
   sentence break between `{M}` and `{S}`, how many distinct quantity kinds, at most two
   number-dependent templates.
7. **Show the file schema exactly**, with every key.
8. **Give good examples in English, and bad examples with the reason each is refused.**
   Tell the writer never to copy or translate the examples (the validator's novelty check
   enforces it).
9. **End with the validator loop and the reply format.** "Run the validator until it prints
   `VALIDATE ok 12`. Fix every line by rewriting the template properly, never by weakening
   it. When it passes, reply with the validator's last line and nothing else." A short,
   fixed reply is easy to check and costs nothing.
10. **Put language-specific rules in a separate add-on** (section 6 is the example), so the
    main brief stays the same for every language.

### 5.2 The verifier brief

1. **Blind by construction.** The verifier reads only its blind file. Name what it must
   never open (the keys, the writers' files, other verifiers' outputs, real problem sets).
2. **Judge only the words.** Tell it not to guess the author's intent and not to match texts
   up (they are shuffled).
3. **Never tell it what to expect.** No expected agreement rate, no "most of these are
   fine". A verifier that knows the target drifts towards it.
4. **Ask closed questions** with a fixed vocabulary (op, operands, role, signed_natural, a
   fixed list of flags), plus a free-text note only when it flags something. Closed answers
   can be compared with the writer's labels automatically.
5. **Give it a format checker** that knows the format and not the answers, and make it loop
   on that until `FORMAT ok`.
6. **One strong verifier per 4-5 languages** is the size that worked for us: enough texts
   per agent to be worth the brief, few enough languages to judge each one carefully.

### 5.3 Checking that the briefs worked

After every batch, check that every expected output file exists and passes its checker
before you count the batch as done. An agent that answered a question instead of writing,
or wrote to the wrong path, shows up only there.

---------------------------------------------------------------------------------------

## 6. The numeral-agreement lesson (Russian and Ukrainian)

Every slot is filled with any whole number from 1 to 999,999, and many languages change the
words next to a number depending on the number. In Russian, "5 велосипедов" (genitive
plural) but "2 велосипеда" and "1 велосипед"; the verb can agree too. So a template that
reads perfectly with 40 can be ungrammatical with 21.

The first instinct, ours included, was to ask writers to avoid that entirely. It went
wrong. In rounds 1-3 the verifier kept only 19 of 36 Russian and 24 of 36 Ukrainian
templates, against 29-36 of 36 in every other language, because the writers had dodged
agreement with roundabout officialese ("в количестве {M} упаковок", "кількість ..., що
становить {M}"), and the verifier, correctly, flagged those as unnatural. An unnatural
flag drops a template.

The fix was to make honesty free:

1. The writer **declares** each template `invariant` (no word changes with the number) or
   `number_dependent`, and states the rule in `agreement_note` either way.
2. The validator caps number-dependent templates (at most 2 of 12).
3. The verifier flags `number_dependent_grammar` independently, whatever the writer said.
4. **That flag alone never drops a template**; it keeps it and tags every row `numdep`,
   so a quoted number can leave those rows out (`gen_v5.py --numdep drop`). An `unnatural`
   or `ungrammatical` flag does drop it.

So an honest declaration costs nothing, a false "invariant" gains nothing (the verifier
flags it anyway), and a circumlocution loses the template. The add-on
(`ADDON_v5_writer_ru_uk.md`) lists what does work naturally: a unit abbreviation after the
number (кг, л, км, грн), a label and a colon ("Выдано книг за неделю: {M}."), a label and a
dash inside a list ("утром — {M}, днём — {S}"), and, a few times per unit at most, "число X
составило {M}". Where the natural sentence has a counted noun right after the number, write
the genitive plural (right for numbers ending in 0, 5-9 and 11-14) and declare it. Never use
a clause bent out of shape to move the number, clock times or dates written as words (they
are hidden numbers), or an extra sentence that opens by pointing back at the facts ("Тем же
утром", "Ще"), because extra sentences are placed before, between or after the facts and
must stand alone. With the add-on, rounds 1-5 ended with 41 of 60 Russian and 46 of 60
Ukrainian templates kept.

The general lesson, for every language: **ask writers to declare a property honestly and
let a blind reader check it; never ask them to make a property impossible to observe.**

---------------------------------------------------------------------------------------

## 7. Language-specific pitfalls found so far

**Digits of other scripts.** The generator writes ASCII digits, and the locator reads ASCII
digit tokens only. A Bengali writer once wrote the distractor in Bengali digits (২৫০ for
250): a text-level check saw three numbers, the token locator saw two, and 48 of 100
Bengali texts silently became easy two-number rows. So templates may contain **no digit
of any script**, and `exact_block/numerals_ml.py` has `non_ascii_digits()` and
`to_ascii_digits()` for checking and converting text that did not come from the generator.
The languages whose own digits a checker must expect: Arabic (Arabic-Indic), Persian and
Urdu (Extended Arabic-Indic), Hindi, Marathi and Nepali (Devanagari), Bengali, Punjabi
(Gurmukhi), Gujarati, Tamil, Telugu, Kannada, Malayalam, Sinhala, Thai, Tibetan, Burmese,
Khmer, Mongolian (traditional script), and fullwidth digits in Chinese, Japanese and Korean.
Amharic's Ethiopic numerals are not positional digits at all and cannot be converted.

**Separators.** The generator writes plain digit runs, but prose written by a person groups
thousands with a comma, a dot or a space depending on the language, and uses the comma as
the decimal mark in most of Europe. `numerals_ml.py` has the per-language table; see the
README's coverage table.

**No spaces between sentences.** Japanese and Chinese join sentences without a space; the
generator knows this for `ja` and `zh` (`NOSPACE`). Thai, Burmese and Khmer write no
spaces between words; a question in Thai may end with a question word instead of a
question mark (the validator allows it).

**Script sanity.** Japanese text must contain kana (or it reads as Chinese); Chinese must
not. Ukrainian must contain і, ї, є or ґ somewhere in the unit, Russian must not. Persian
must contain Persian letters (ی ک پ چ ژ گ) or it reads as Arabic. The validator checks all
of these.

**Agreement with the number.** Slavic, Baltic and Finnic languages, Arabic and Hebrew:
declare `number_dependent` honestly (section 6). After Russian and Ukrainian, Greek, German,
French and Italian lost the most templates in rounds 1-5 (47, 50, 51 and 51 of 60 kept,
against 55-59 of 60 in most languages).

**Classifiers.** Chinese, Japanese, Korean, Thai, Vietnamese, Burmese: use a classifier or
counter that works for every integer.

**Number words hide numbers.** "Two", "half", "twice", "dozen", "pair", and ordinals ("the
first shift") are all hidden operands and are refused. The per-language lists are
deliberately conservative: words that are also ordinary words (Italian "sei" = "you are",
Hindi "दो" = "give", Persian "نه" = "no", Bengali "নয়" = "is not", Thai "สาม" inside longer
words) are left out rather than refused everywhere.

**Latin** uses ASCII digits, never Roman numerals.

**Right-to-left scripts** (Arabic, Hebrew, Persian, Urdu) are fine: the slots are ASCII and
the locator finds digit runs in any direction.

**Questions that presuppose a sign.** "How much is left?" and "how many fewer?" assume the
answer is positive, so they cannot carry the negative twin. In the older banks this was the
largest single cause of rejection (236 of 262 rejections when the second 25 languages were
added). A signed subtraction question must ask for a change or a difference with a stated
direction ("what was the change from January to March?", "what is the balance?").

**Division.** Never mention leftovers or remainders, and never ask how many are "needed"
(that means rounding up). The words must say which number is divided; "the quotient of X
and Y" does not. And do not force exactness with contorted phrases: simply ask how many
bags were filled, because the generator fills the dividend with an exact multiple anyway.

**Same frame, new nouns.** The older Chinese, Japanese, Arabic and German template sets
contain pairs of stories with the same frame and different nouns (overlap 0.54-0.65 on the
near-duplicate measure). v5's 0.45 threshold refuses those; expect writers in those
languages to need a second attempt more often.

**Weak languages for the model itself.** In Yoruba, Georgian, Khmer, Burmese, Zulu, Hausa
and Amharic the 8B host we measured often cannot do the arithmetic at all, and every reader
of its internal state is weakest there too. That is a finding about the model, not a bug in
your bank.

---------------------------------------------------------------------------------------

## 8. What makes a hard distractor

### 8.1 The measurements

A **pair reader** is a small read-out that looks at a language model's internal state
while it reads a problem and says which two of the numbers the question uses. The
measurements below are for the simplest one, a **band reader** with no trained parameters
at all: it picks the two numbers that the model's attention, from the position where the
answer starts, concentrates on, averaged over a band of middle-to-late layers. They were
made on bank v4's bank A (25 languages, Qwen3-8B as the host), comparing rows that have a
layout ("exposed") with rows that do not ("unexposed"). Each hypothesis was written down,
with its test and its threshold, before the numbers existed. A **miss** means the reader's
pair is not the gold pair.

| layout | reader misses, exposed | reader misses, unexposed |
|---|---|---|
| a distractor written **between** the two operands | 371/628 (59.1%) | 194/462 (42.0%) |
| the distractor written **after** the pair rather than before it | 1,783/5,232 (34.1%) | 579/5,232 (11.1%) |
| the same, on the multi-distractor rows where the placement is drawn per row (the clean version, see below) | 550/1,150 (47.8%) | 155/1,158 (13.4%) |
| the **largest** number in the row is a distractor | 926/2,824 (32.8%) | 846/3,560 (23.8%) |
| rows where **the host model itself** attributes its answer to a wrong pair | 414/670 (61.8%) | 323/1,586 (20.4%) |

and one more: of the band reader's misses on the 4-5-number rows, **2,959 of 3,232
(91.6%) keep exactly one of the two gold numbers**. A miss is almost never a wild guess; it
is the right partner of one operand swapped for a look-alike.

Two cautions come with these numbers.

* **The "after" result on three-number rows is confounded.** In bank v4 the generator puts
  the single distractor sentence before the facts for two of a story's four distractor
  number categories and after the facts for the other two, so "after" rows also carry
  different numbers. The multi-distractor rows draw the placement independently of the
  numbers, and there the gap is larger, not smaller, which is what a real recency effect
  predicts and a number-category artefact does not.
* **Trained readers behave differently.** A reader fitted on three-number rows missed
  *fewer* rows when the distractor came after the pair (291/5,232, 5.6%) than before it
  (488/5,232, 9.3%): the opposite direction. It learned something about position that the
  zero-parameter reader does not have. So always report which reader a difficulty claim is
  about.

On a set of real word problems (test only) the same layouts were the hardest ones too.
And the host model itself shows the same gradient: when it answers, its own answer can be
attributed to the right pair on 1,922 of 1,923 rows with an easy distractor placed before
the facts, 1,628 of 1,685 with a same-length one, but only 974 of 1,202 with a same-kind
sentence before the facts and 717 of 827 with one after them.

### 8.2 What this means for templates

Put together: **a distractor is hard when it is the same kind of quantity as one of the
operands, sits where an operand could sit, and is a plausible partner for the other
operand.** Size helps a little (a large distractor fools a reader that has a magnitude
habit), position helps a lot (between the operands, or after them), and a distractor the
host model itself falls for is the hardest of all. The v5 design turns these into explicit
axes on every row (`d_rungs`, `d_positions`, `d_tiers`), so you can measure them per
language and per operation instead of hoping.

The **similarity ladder** v5 uses, easiest first:

| rung | the distractor is | where it comes from |
|---|---|---|
| L0_kind | a number of a different kind and a different owner (a room or route number) | `ex_sentence` |
| L1_owner_sent | the same kind and unit, another owner, in its own sentence | `sem_sentence` |
| L1_owner | the same kind and unit, another owner, inside the facts | `{T}`, shape `diff_owner` |
| L2_time | the same owner at another time | `{T}`, shape `other_time` |
| L3_list | a member of a same-kind list; the question picks two (add, sub) or one plus the other operand (mul, div) | `{T}`, shape `list` |

### 8.3 Recipes

**A distractor between the two operands.** Give the facts a sentence break between `{M}`
and `{S}` (v5 requires this in at least 6 of every 12 templates, in both bases), so an
extra sentence can be dropped in between; or put `{T}` in the middle of a list.

```
facts_first: This morning the dairy bottled {M} litres of whole milk, {T} litres of buttermilk and {S} litres of cream.
question   : How many litres of whole milk and cream did the dairy bottle this morning?
```

**A distractor after the pair.** Write `sem_sentence` so it reads naturally at the end, and
write the question so it can come first: the generator places sentences before, between or
after the facts and asks the question first or last. A same-kind, other-owner sentence at
the end is the hardest single-sentence placement we measured.

```
sem_sentence: The cooperative across the valley bottled {D} litres of whole milk that morning.
```

**The largest number is a distractor.** You do not choose the values; the generator
balances the distractor's rank so that it is the largest number on about a third of rows.
What you control is plausibility: a distractor that can naturally be large (a rival's
total, last year's figure, the whole warehouse beside one shelf) without its size giving
it away. Keep it the same kind and unit as an operand, so the value tier `V1_same_len`
(same number of digits as an operand) or `V2_near` (within a tenth of it) is believable.

```
facts_first: Last season the orchard picked {T} kilograms of apples. This season it picked {M} kilograms and sold {S} kilograms at the market.
question   : How many kilograms of this season's apples were not sold at the market?
```

**Four or five numbers.** Every v5 template already makes these rows (T+s: 4 numbers, T+ex+sem:
5), from the look-alike in the facts plus one or both extra sentences. What makes them hard
is that each extra number is a plausible partner of one operand. For mul and div, say which
operand the look-alike mimics (`t_mimics`: a rival count of groups is `M`, a rival group
size is `S`) and write both kinds within a unit.

```
facts_first: The school hall has {M} long rows of chairs with {S} chairs in each; the short rows hold {T} chairs each.   [mul, t_mimics S]
question   : How many chairs are there in the long rows?
```

(Name the group in the question's words, never through a hypothetical such as "if every
row were a long row": a verifier rightly calls that ambiguous.)

**And the one thing never to do:** a distractor that can be excluded without reading the
question (a different unit, an obviously different kind of thing, a year). That is rung
L0, useful as the easy control, and nothing more.

---------------------------------------------------------------------------------------

## 9. A worked example, start to finish

Suppose `status_v5.py --next` hands a writer the unit `W5-en-u05`, topics
`library_loans, bookshop, printing_press`, and says `{T}` goes in the middle for the
`sub/other_time` cell. Here is one of its 12 templates (written for this guide; the real
`W5-en-u05-05` in the shipped bank is a different story, which you can print with
`python data_gen/show_prompts.py --template W5-en-u05-05`):

```json
{"id": "W5-en-u05-05", "op": "sub", "shape": "other_time", "topic": "library_loans",
 "quantity_kind": "books on loan", "unit": "books", "verb": "lend",
 "facts_first":  "On Friday evening the branch library had {M} books out on loan, on Wednesday evening {T}, and on Monday evening {S}.",
 "facts_second": "On Monday evening the branch library had {S} books out on loan, on Wednesday evening {T}, and on Friday evening {M}.",
 "base_first":   "On Friday evening the branch library had {M} books out on loan. On Monday evening it had {S}.",
 "base_second":  "On Monday evening the branch library had {S} books out on loan. On Friday evening it had {M}.",
 "question":     "By how much did the number of books on loan at the branch library change from Monday evening to Friday evening?",
 "ex_sentence":  "The branch library occupies unit {D} of the shopping arcade.",
 "sem_sentence": "The university library across town had {D} books out on loan on Friday evening.",
 "t_mimics": "both", "signed": true, "sign_convention": "Friday evening minus Monday evening",
 "div_mode": "", "numeral_grammar": "invariant",
 "agreement_note": "'books' follows every slot; English plural agreement fails only for the value one, accepted as in every bank.",
 "gloss_en": "(English already)", "notes": "Wednesday is the look-alike: same library, same quantity, another day."}
```

**Validate.** The writer runs `validate_v5.py` on its file. Say it first wrote the
question as "How many more books were on loan on Friday?": the validator does not catch
that (it is grammatical and has no number), but it presupposes a positive answer, and the
verifier would later read it as not signed-natural, demoting the template. The writer
changes it to the "by how much did ... change from ... to ..." form above, and the file
prints `VALIDATE ok 12`.

**Accept.** `status_v5.py --accept` compares the 12 templates with every accepted English
template; none overlaps at 0.45 or more, so the unit is stamped accepted.

**Blind.** `make_blind_v5.py V5-g1-u05` turns this template into four texts. The "first"
text becomes, with the slots renamed in order of appearance:

```
On Friday evening the branch library had {A} books out on loan, on Wednesday evening {B}, and on Monday evening {C}. By how much did the number of books on loan at the branch library change from Monday evening to Friday evening?
```

and the key file records that `{A}` is the writer's `{M}`, `{B}` is `{T}`, `{C}` is `{S}`.

**Verify.** The verifier, seeing only that text (shuffled among 239 others), answers

```json
{"id": "V5-g1-u05-t117", "op": "sub", "operands": ["A", "C"], "role": "A", "signed_natural": true, "flags": [], "note": ""}
```

**Check and clean.** `check_v5.py --report` maps the letters back through the key: op sub
= sub, operands {A, C} = {M, S}, role A = M, signed natural = signed. If the other three
texts of the template agree too and carry no flag, `--clean` keeps it.

**Generate.** `gen_v5.py` fills the template 24 ways. Two of them, the twins of one T-arm
row (numbers illustrative):

```
On Friday evening the branch library had 1406 books out on loan, on Wednesday evening 1391, and on Monday evening 1377. By how much ... ? The answer is      a=1406 b=1377 ans=29   kind=pos
On Friday evening the branch library had 1377 books out on loan, on Wednesday evening 1391, and on Monday evening 1406. By how much ... ? The answer is      a=1377 b=1406 ans=-29  kind=neg
```

Each row records `d_rungs = ["L2_time"]`, `d_positions = ["between"]`, the value tier of
1391 (`V2_near`: within a tenth of an operand), the written order, and every pair's result
under subtraction (1406 - 1391 = 15, 1391 - 1377 = 14, 1406 - 1377 = 29), so a model's
answer can be attributed to exactly one pair.

**Use it with the block in this repo.** The block has no sign channel, so
`data_gen/bank_to_corpus.py` keeps the `kind=pos` twin (answer 29) and leaves the negative
one for the pair and role readers; see the README.

---------------------------------------------------------------------------------------

## 10. Looking at the prompts

Before you train on a bank, write a template, or believe a number measured on one, read
some of its rows. `data_gen/show_prompts.py` streams a bank line by line (the 290 MB v5
file is fine) and prints rows, one template's variants, or counts. It reads every bank in
`banks/`; the default is bank v5, so regenerate that first (`python banks/make_v5.py`, see
[V5_TOOLS.md](V5_TOOLS.md)).

**Print a few rows.** Each row is printed as its full text (the prompt, ending in the
language's "The answer is"), the English gloss of the template, and one line of labels:
the operation, `a` and `b` (for sub the minuend and the subtrahend, for div the dividend and
the divisor), the answer, the distractor values `ds`, `kind` (pos, or neg when the answer is
negative), `variant` (which operand is written first), the number of numerals, and for v5
the arm, the distractor rungs, positions and value tiers.

```bash
python data_gen/show_prompts.py                          # the first 5 rows of bank v5
python data_gen/show_prompts.py --random -n 10           # 10 rows drawn at random (seeded: --seed 1 for others)
python data_gen/show_prompts.py --lang ta --random -n 3 --fields quantity_kind,shape
```

**All the variants of one template.** A v5 template becomes 24 rows (section 3.9): the
base arm, the look-alike arm in two value tiers, each extra sentence alone, and the four-
and five-number arms, each in both written orders and both twins. Printing them side by
side is the fastest way to see what the generator does with a template, and whether a
sentence you wrote still reads naturally when it is moved before, between or after the
facts.

```bash
python data_gen/show_prompts.py --template W5-en-u05-05          # the 24 rows, grouped by arm and order
python data_gen/show_prompts.py --template W5-ru-u03-02 --arm T  # only its 8 look-alike rows
```

Template ids are `W5-<lang>-uNN-KK` (unit NN, template KK). For the older banks, which have
no template ids, a template is named by the first four parts of its row id, such as
`sg:ta:A:3` (bank A, story 3 of Tamil) or `sgw:en:A:12` (v4wild).

**Filter by distractor kind.** In v5, `--rung` selects the similarity rung (section 8.1:
`L0_kind`, `L1_owner_sent`, `L1_owner`, `L2_time`, `L3_list`), `--position` where a
distractor sits (`before`, `between`, `after` the two operands), `--tier` how close its value
is (`V0_len`, `V1_same_len`, `V2_near`), `--arm` the row type (`base`, `T`, `ex`, `sem`,
`T+s`, `T+ex+sem`) and `--shape` the template's shape. In v3 and v4 the equivalent is
`--hardness` (`easy`, `matched`, `sem1`, `sem2`, `multi2`, `multi3`, and `wildT` in v4wild).
A row matches `--rung` or `--position` when any one of its distractors does.

```bash
python data_gen/show_prompts.py --rung L3_list --position between --random -n 5    # a list-mate between the operands
python data_gen/show_prompts.py --bank banks/v4/signed_A_int.jsonl --hardness sem2 --lang de -n 3
```

**Filter by numeral count, tags, language, operation, sign.** `--numerals 4,5` (numbers
written in the text, 2 to 5), `--tag numdep` or `--tag demoted` (the verifier tags of
section 3.8; `--tag none` keeps only untagged templates), `--lang ru,uk`, `--op div`,
`--kind neg`, `--variant sub_first`, and `--grep` for a literal piece of text. Every filter
takes a comma-separated list and all filters combine with "and".

```bash
python data_gen/show_prompts.py --tag numdep --lang uk --random -n 5     # what number-dependent grammar looks like
python data_gen/show_prompts.py --op sub --kind neg --numerals 5 -n 3    # negative answers among five numbers
```

**Count instead of print.** `--count` takes field names and prints how many matching rows
have each combination, which is how you check a claim like "every language has both written
orders in every rung" before relying on it.

```bash
python data_gen/show_prompts.py --count lang,dist_arm
python data_gen/show_prompts.py --op div --count d_rungs,variant
```

**Is my new template a near copy of a shipped one?** The accept step (section 3.5) compares a
unit only with units accepted in your own `accept/` folder, and a fresh clone has none: the
working folders of the finished bank are not shipped. So compare a new writer file with the
4,352 shipped templates of its language directly; it uses the same text and the same 0.45
threshold as the validator:

```bash
python data_gen/show_prompts.py --novelty banks/v5/writers/en/W5-en-u17.json
```

It prints one line per template (`ok` or `NEAR`, the highest overlap, and the shipped
template it overlaps with) and exits with 1 if any template is at or above the threshold.

If you want something the script does not do, the rows are plain JSON lines, one object per
line; the field list is in `banks/README.md` and in the docstring of `banks/v5/gen_v5.py`.

---------------------------------------------------------------------------------------

## 11. Generating data with Claude, step by step

This is the procedure for adding templates to bank v5 with Claude Code driving the agents:
Sonnet agents write, Opus agents verify, and you check the files between the two. The
procedure is written as steps and checks, not as prompts to paste: your prompts will
differ, and what matters is what each step must guarantee. Sections 3 to 5 explain the
tools and the briefs; this section is the order to run them in.

### 11.1 Before the first round

1. **Regenerate and check.** `python banks/make_banks.py` (14/14) and
   `python banks/make_v5.py` (6/6). Then run the six selftests
   (`python banks/v5/<tool>.py --selftest` for `host_attr_v5`, `validate_v5`, `gen_v5`,
   `status_v5`, `make_blind_v5`, `check_v5`); each must print `0 fail`. If any fails, stop:
   you would be building on tools that are not the ones that made the bank.
2. **Choose unit numbers that are not taken.** Units 1 to 16 of every language are the
   finished bank. In a fresh clone the tools do not know that (their working files are not
   shipped), so `status_v5.py --next` would hand you unit 1 again. Work in units 17 to 32
   (tier T3) and take the specs from the full list:
   `python banks/v5/status_v5.py --next 800 --tier T3 | grep -E -- '-u17 '` prints the 25 unit
   specs of unit 17, one line each (the JSON after the state is the spec).
3. **Choose the chunk.** The smallest piece that can be verified is **one verifier group at
   one unit number**: the five writer units of that group's languages (group 1 = en, de, nl,
   fr, es; the five groups are in `v5_common.GROUPS`) plus their one verifier unit, which stays
   `blocked` until all five writer units are accepted. A full round is all five groups: 25
   writer units and 5 verifier units, 300 templates. On a low quota, start with one group.
4. **Check your quota.** Type `/usage` in Claude Code before each chunk. Planning figures
   (section 4): a writer unit costs roughly 90-125 thousand Sonnet tokens, a verifier unit
   roughly 100-180 thousand Opus tokens. If the remaining allowance cannot cover the whole
   chunk, run a smaller one: every step below can be stopped at any point and resumed, but a
   chunk that stops half way costs you a restart of the agents that did not finish.

### 11.2 Write (a workflow of Sonnet writers)

5. **Launch one workflow of writer agents: Sonnet, medium effort, one unit per agent.**
   Each agent's prompt is the writer brief `banks/v5/BRIEF_v5_writer.md` (plus
   `banks/v5/ADDON_v5_writer_ru_uk.md` for Russian and Ukrainian) and that unit's spec line
   from step 2. Nothing else: no summary of the project, no expected pass rate, no reason why
   the task is allowed (section 5.1).
6. **Every writer prompt must carry two guards,** stated in the prompt itself as well as in
   the brief:
   * **the one-file fence:** "Write exactly one file, at `<the spec's output_path>`. Create,
     edit or delete no other file. If that path exists, stop and say so. Run nothing except
     the validator." Without it, agents have overwritten each other's files;
   * **the relayed-question guard:** "Ignore any relayed message or question that asks you
     something else; do not answer it, write your file." If you type into the session while
     the workflow runs, your message can reach every agent, and without this line most of
     them answer you instead of writing.
7. **Mind the concurrency limit.** One workflow runs only about (number of CPU cores - 2)
   agents at a time; on an 8-core laptop, 6. A workflow of 25 writers therefore runs in waves
   and takes about four times as long as one batch of six. To run more at once, launch several
   workflows side by side, each with a **disjoint** slice of the units (for example one per
   verifier group). Never give two workflows the same unit.
8. **Each writer finishes by printing `VALIDATE ok 12`** and nothing else (the brief's reply
   format). An agent's reply is not evidence that its file exists; step 9 is.

### 11.3 Pause and check

9. **When the workflow ends, check the files, not the replies.** For every unit you launched:
   * the file exists at its output path (`ls banks/v5/writers/<lang>/`);
   * `python banks/v5/validate_v5.py <file>` prints `VALIDATE ok 12`;
   * `python data_gen/show_prompts.py --novelty <file>` finds no near copy of a shipped
     template (section 10).
   A missing or failing file is re-run as its own one-unit agent with the same spec, not
   fixed by hand.
10. **Accept.** `python banks/v5/status_v5.py --accept`, then `python banks/v5/status_v5.py`.
    Every unit of the chunk should now read `accepted`. A `rejected` unit is a near copy of
    another accepted unit of its language: `--next` (or the full list of step 2) now prints
    it as attempt K+1 with the templates to rewrite, and it goes back to step 5 alone.
11. **Stop here if the quota is low.** Nothing is lost: the accepted units are files, and the
    next session starts at step 12. Type `/usage` before going on.

### 11.4 Verify (a workflow of Opus verifiers)

12. **Blind.** `python banks/v5/make_blind_v5.py V5-gG-uNN` for each verifier unit whose five
    writer units are accepted (`status_v5.py` shows it as `ready`; `--ready` blinds all of
    them). This writes `blind/V5-gG-uNN.blind.json` and the key to `blind_key/`.
13. **Launch one workflow of verifier agents: Opus, medium effort, one verifier unit per
    agent.** Each agent's prompt is `banks/v5/VERIFY_v5.md` and the paths of its blind file
    and its output file (`banks/v5/verify/V5-gG-uNN.json`), with the same two guards as
    step 6. The prompt must name only the blind file: never the writers' files, the key, the
    writer brief, or what you expect the answers to be (section 5.2). One verifier covers one
    group of five languages, 240 texts.
14. **Each verifier finishes with `FORMAT ok <n>`** from
    `python banks/v5/check_v5.py --format <blind file> <output file>`.

### 11.5 Pause, check, clean, generate

15. **Check the files again:** every verify file exists and passes `check_v5.py --format`.
    Re-run a missing one as a single agent.
16. **Report.** `python banks/v5/check_v5.py --report` writes `VERIFY_REPORT_v5.md` (agreement
    per language on op, operands, role and sign, and the flags) and
    `VERIFY_DISAGREE_v5.jsonl` (every disagreement). Read the disagreements of any language
    whose agreement is well below the others before you clean: they are usually one habit
    of one writer, and the fix belongs in the brief or its add-on for the next round.
17. **Clean.** `python banks/v5/check_v5.py --clean --out banks/v5/clean/clean_mine.json`
    keeps, drops, tags and demotes each of your templates by the rules of section 3.8.
18. **Generate.** `gen_v5.py` reads one clean file. To make a bank of the shipped templates
    plus yours, first rebuild the shipped file from its per-language parts
    (`python banks/make_v5.py --join-only`), then join the two `kept` lists into a new file
    (the template ids of units 17 and up cannot collide with the shipped ones):

    ```python
    import json
    base = json.load(open("banks/v5/clean/clean_v5_r1-16.json", encoding="utf-8"))
    mine = json.load(open("banks/v5/clean/clean_mine.json", encoding="utf-8"))
    both = {"kept": base["kept"] + mine["kept"], "dropped": base["dropped"] + mine["dropped"], "pending_units": []}
    json.dump(both, open("banks/v5/clean/clean_plus_mine.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ```

    then `python banks/v5/gen_v5.py --clean banks/v5/clean/clean_plus_mine.json --out-dir
    banks/v5/bank_plus --min-cell 500`. It prints the audit (row-level violations must read
    NONE) and writes `SHIP_V5.raw.md5`. Your bank's md5s will not be those of `SHIP_V5.md5`,
    by design: the shipped bank stays the reference that every quoted number was measured
    on, so say which bank a number comes from.
19. **Look at it** with `show_prompts.py --bank banks/v5/bank_plus/signed_A_int.jsonl`
    (section 10) before you train on it.

### 11.6 Chunked, resumable rounds on a low quota

The steps above are one chunk. For a longer run, repeat them with these rules (section 4
explains why the tools make them safe):

* **One chunk per usage window.** Size the chunk from `/usage`: if a window allows about one
  group, run one group (5 writers, then 1 verifier) per window. A write half and its verify
  half need not share a window, since step 11 is a clean stopping point.
* **Check `/usage` between chunks, never during one.** A chunk interrupted by the limit is
  not lost (every finished file stays), but its unfinished agents must be re-run from the
  start of their unit.
* **Resume from the files.** Start every session with `python banks/v5/status_v5.py`; it
  recomputes each unit's state from what is on disk. Units that are `pending` or `invalid`
  are re-run; `valid` ones go to `--accept`; `ready` verifier units go to step 12.
* **Keep fan-outs small and split.** Fewer agents at once, and several disjoint workflows
  rather than one large one, is both faster (step 7) and gentler on a small quota than one
  wide launch; spreading chunks over the day helps too.
* **Keep a one-line log per chunk** (date, units, files checked n/total, accepted n/total,
  verified n/total), so the next session, or a teammate, knows where to start without
  re-reading anything.

---------------------------------------------------------------------------------------

## 12. The older pipeline (banks v2 to v4), for reading the old files

The v2-v4 banks were built with the same idea in a simpler form, one language per writer:

| step | v2-v4 | v5 |
|---|---|---|
| templates | `writers/<code>.json`, 20 stories (16 bank A + 4 bank B), at least 5 domains | `writers/<lang>/W5-*.json`, 12 per unit |
| blind | `make_blind.py --codes <code>` (placeholders renamed, filled two ways) | `make_blind_v5.py` |
| verify | one verifier per 4-6 languages, `verified/<code>.verify.json` | `verify/V5-*.json` |
| merge / clean | `merge_verify.py` (no arguments, deterministic, rebuilds every language) -> `verified/<code>.verified.json` | `check_v5.py --clean` |
| distractor sentences | two more writers per language -> `distfact/`, `distfact2/`, checked by `validate_distfact.py` | inside each template (`ex_sentence`, `sem_sentence`) |
| generate | `gen_signed_bank_ml.py --bank-version v3/v4` | `gen_v5.py` |

Adding a language to the old banks was: a writer file, a blind verifier, `merge_verify.py`
(then check that no older language's `verified/` file changed: keep an md5 list before and
after), the two distractor passes, and a regeneration. Expect 60-80% of a writer's stories
to be accepted. Remember that the generator takes every `verified/` file it finds, so a
new language changes the bytes of a bank regenerated without `--langs`; that is why
`banks/make_banks.py` pins its language lists.

---------------------------------------------------------------------------------------

## 13. House rules

* **Real word-problem sets are test sets only.** Nothing is fitted, selected, tuned or
  written from them, and no writer or verifier opens them.
* **Quote every count with its denominator** (371/628, not "371 misses").
* **Print the easy baselines beside every result**: the size rule and the first-written
  rule (each exactly half on these banks), and a text-only reader that never looks at the
  model. If your reader lands near the text-only one, it is reading the words, not the
  model.
* **Every new generator version must reproduce every earlier bank byte for byte** under
  its old flags. Print the md5s; if one moves, you changed something you did not mean to.
* **Keep all state interruptible.** Any job, agent or script should be safe to stop at any
  instant and resume from its files.

---------------------------------------------------------------------------------------

## 14. Banks added after v5

These were built with the same writer -> validate -> close -> blind verify -> clean ->
generate pipeline as v5 (sections 2-5), one tool per bank. What is shipped is the clean
templates (kept and dropped, with the verifier's reasons) and, wherever the tool runs on
its own in this repository, the tool and the md5s of the rows it generates. The writer
and verifier briefs, the blind files and their answer keys are not shipped. Counts and
layouts are in [`banks/README.md`](../banks/README.md).

* **`banks/subrole/`** (English, subtraction): the minuend is smaller in half the rows and
  written second in half the rows, so neither size nor order names it. 190 templates,
  6,080 rows; `python banks/make_role_banks.py subrole` regenerates them byte for byte.
  Writing for it is the lesson of section 8 turned around: the role must sit in the
  words of the facts ("this week it holds {M}", "last week it held {S}"), in its own
  clause, and the question must read naturally with a negative answer ("What was the
  change ... from last week to this week?", never "how many more" or "the difference").
* **`banks/subrole_g3/`** (English, subtraction): 33 more templates in the same design,
  for testing only (`fold = -2`): score a reader fitted on `subrole/` on them, never fit on
  them. 3,036 rows; `python banks/make_role_banks.py subrole_g3`.
* **`banks/divrole2/`** (English, division): the dividend is smaller in half the rows (the
  answer is then a proper fraction, 3/8) and written second in half the rows. 164
  templates in folds 0-4 plus 20 reference templates in fold -1, 5,888 rows;
  `python banks/make_role_banks.py divrole2`. A division template must read naturally with
  a fractional answer: 3/8 of a litre each is fine, 3/8 of a bus is not, so the frames are
  shares of an amount, rates and unit prices, never a count of whole things.
* **`banks/v5x/`** (PARTIAL): bank v5 extended to the 36 languages of v3_61 that v5 lacks,
  with a question-form axis (F0-F7: plain, question first, instruction, conditional,
  indirect, casual, fill-in-the-blank, dialogue). Only chunk C1 is
  done: Bulgarian, Czech, Hungarian, Romanian, Slovak and Serbian, 274 templates, 6,576
  rows; `python banks/make_v5x.py`. The tool, `v5x.py`, wraps the v5 tools of section 4
  unchanged and adds the form rules, so writing a v5x unit is writing a v5 unit with one
  more field per cell.
* **`banks/abstainbank/`** (English, AB1): 503 templates of questions the block should
  abstain on (20 classes: percent, roots, remainders, averages, two- and three-step
  questions, rounding, dates, yes/no ...), each with a one-step twin over the same facts.
  Templates only: the project's filling tool does not run on its own here, and
  `banks/README.md` says how to fill them. The lesson of its re-pilots is the one of
  section 8 from the other side: if the abstain question and its twin can be told apart
  by their words alone, a gate trained on them learns the words. Write the twin in the
  abstain question's vocabulary.
