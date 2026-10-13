---
name: cafe-outing
description: Plan a trip to one of the user's cafes. Pick the best one to go to now or at a given time, from where they are, for a given drink. Use for "where should I go for coffee", "which cafe should I go to", or "somewhere open near X with a cheap flat white".
---

# Cafe outing

Follow these steps in order. Skip a step only when it says so.

1. **Where.** If the user named a place or postcode, call `locate`.
   If they want somewhere near them but gave no place, ask for one and stop.
   If they don't care about distance, skip this step and step 3.
2. **When.** Call `open_shops`: with `date`/`day`/`time` if they gave one, otherwise with no arguments (right now).
   Only recommend cafes that are open then.
3. **Distance.** Call `nearest_shops` with the lat and lng from `locate`.
4. **Drink.** If they named a drink, call `compare_prices` with it.
5. **Menu or specials.** Only if they asked: call `ask_cafe_website` with a question that names the cafe you are about to recommend.
6. **Choose one cafe.** Prefer, in order: open, then the shortest walk (if there is a location), then the cheapest for their drink, then the user's own rank.
7. **Answer** using the format in the `references/ANSWER_FORMAT.md` resource.