# BANK v5 writer add-on: Russian and Ukrainian (numbers and the words around them)

This add-on is for writers of Russian (`ru`) and Ukrainian (`uk`) units: the rewrite units `R5-ru-*` / `R5-uk-*` and
the ordinary units `W5-ru-*` / `W5-uk-*` from round 4 on. It adds to `BRIEF_v5_writer.md`, section 2 ("Grammar that
depends on the number") and section 3. Where the two differ, this add-on wins. Everything else in the brief stands.

Why it exists: in rounds 1-3 the blind verifier kept Russian 19/36 and Ukrainian 24/36 templates, against 29-36/36
in every other language. The writers had avoided number agreement with roundabout phrases, and the verifier read
those phrases as unnatural. An unnatural flag drops a template; an honest number-dependence flag does not.

## 1. How `number_dependent` works (exactly what the tools do)

1. **You declare it.** Each template has `numeral_grammar`: `"invariant"` (no word changes with the number) or
   `"number_dependent"` (some word next to a slot has to change form for some numbers). Write the rule in
   `agreement_note` either way.
2. **The validator caps it.** At most 2 of the 12 templates of a unit may be `number_dependent`. In a rewrite unit
   the cap is the spec's `quotas.numdep_max`, which is 1 per 6 templates, rounded up.
3. **The verifier checks independently.** It reads every text blind and flags `number_dependent_grammar` whenever
   the words around a slot would have to change for some numbers, whatever you declared.
4. **That flag never drops a template.** On its own it keeps the template and tags it `numdep`. A flag `unnatural`
   or `ungrammatical` drops the template.
5. **The generator.** Any whole number from 1 to 999999 goes into each slot, and nothing in the words changes. Rows
   of a template that you declared, or the verifier flagged, carry `numdep = true`, so a quoted number can leave them
   out (`gen_v5.py --numdep drop`).

So an honest `number_dependent` costs nothing at verification. Writing "invariant" on a template that is not
invariant gains nothing, because the verifier flags it anyway. A roundabout phrase used to avoid agreement gets
flagged unnatural, and then the template is lost.

## 2. What to write

**Invariant, and natural:**
- A unit abbreviation after the slot: `кг`, `г`, `т`, `л`, `мл`, `км`, `м`, `см`, `га`, `руб.` / `грн`. Use `шт.`
  only for piece goods in a stock, shop or inventory setting, never after a liquid or loose goods.
- A label and a colon, in a tally or report register: the counted noun comes first, then the number.
- A label and a dash inside a list: "утром — {M}, днём — {S}" / "уранці — {M}, удень — {S}".
- "число X составило {M}" / "кількість X становила {M}" is acceptable as report register. Use it in a few
  templates of a unit at most. Never make it the frame of every sentence, and never use it twice in one sentence.

**Number-dependent, declared:** where the natural sentence has a counted noun right after the slot, write that
noun in the **genitive plural**. That form is right for numbers ending in 0, 5-9 and 11-14 (5, 12, 40, 100, 1 000).
It is wrong for numbers ending in 1 other than 11, which need the nominative singular, and for numbers ending in 2-4
other than 12-14, which need the genitive singular in Russian and the nominative plural in Ukrainian. Set
`numeral_grammar` to `"number_dependent"` and put exactly this rule, with your noun's forms, in `agreement_note`.
The verb agrees with the number too when the counted phrase is the subject ("пришло {M} человек" / "прийшло {M}
людей"). That also makes the template number-dependent, so prefer a subject that is not the counted phrase.

If a unit would need more `number_dependent` templates than its cap, rewrite the extra ones with an invariant
construction from the list above. Never fall back on a roundabout phrase.

## 3. Never (these were flagged in rounds 1-3)

Russian:
- `в количестве {X} <noun>` ("... в количестве {M} упаковок"). It is officialese, and it still depends on the number.
- A counted noun fronted in the genitive plural, then a verb, then the slot ("Прививок ... сделали {M}"). This is
  number-dependent, not invariant. If you keep it, declare it, but a plain word order is better.
- `шт.` after a liquid or loose goods ("наполнила воды {S} шт."), and home-made abbreviations such as `ящ.`.
- Relative clauses bent out of shape to move the slot ("которых наш склад хранил {S} ...").

Ukrainian:
- `кількість ..., що становить {X}` / `..., що становила {X}`: a detour through a relative clause.
- `у кількості {X}` / `в кількості {X}` after a noun.
- Russianisms, for example `парковочних` (Ukrainian: `паркувальних`). Use standard Ukrainian words throughout.

Both languages:
- An `ex_sentence` or `sem_sentence` that opens with a word pointing back at something outside it ("Того ж ранку",
  "Тем же утром", "Также", "Ще"). Each extra sentence is placed before the facts, between them or after them, so it
  must make sense on its own.
- Clock times and dates written as words ("о шостій", "в семь утра"). They are hidden numbers.
- Division questions about how many containers were needed or used to take all of something (that means rounding
  up). Ask how many were filled.
- A question that does not name the group its two numbers belong to. The verifier then cannot tell which pair is
  meant.

## 4. Model sentences (for the grammar only; write your own scenes, a copy is refused)

Russian:
- `Утром пекарня израсходовала {M} кг муки, а вечером — {S} кг.` Invariant: `кг` never changes.
- `Выдано книг за неделю: {M}.` Invariant: a label, a colon, then the number.
- `За неделю мастерская отремонтировала {M} велосипедов.` Declared `number_dependent`. The `agreement_note` says:
  "велосипедов (genitive plural) after {M}: right for numbers ending in 0, 5-9 and 11-14; a number ending in 1
  needs велосипед, one ending in 2-4 needs велосипеда".

Ukrainian:
- `Уранці ферма надоїла {M} л молока, а ввечері — {S} л.` Invariant: `л` never changes.
- `Видано книжок за тиждень: {M}.` Invariant: a label, a colon, then the number.
- `За тиждень майстерня відремонтувала {M} велосипедів.` Declared `number_dependent`. The `agreement_note` says:
  "велосипедів (genitive plural) after {M}: right for numbers ending in 0, 5-9 and 11-14; a number ending in 1
  needs велосипед, one ending in 2-4 needs велосипеди".
