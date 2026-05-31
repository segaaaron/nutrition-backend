# NOVA Backend — Domain Context

Authoritative domain language and bounded-context map. **EN canonical**
snake_case identifiers everywhere; display strings via `i18n_translations`.

## Bounded contexts

```
identity → profile → nutrition → recipes → plan → tracking → grocery
                                                ↘ gamification
                                                ↘ coach
                                                ↘ vision
                                                ↘ voice
                                                ↘ notifications
                                                ↘ billing
```

| Context | Aggregate roots | Owns events |
|---------|-----------------|-------------|
| identity      | User, RefreshToken, OtpCode      | UserRegistered, UserLoggedIn, AccountDeleted, DeletionCancelled |
| profile       | UserProfile                      | ProfileUpdated, LocaleChanged |
| nutrition     | NutritionalGoal                  | GoalsRecomputed, MacrosRebalanced |
| recipes       | Recipe (RecipeComponent within)  | RecipeSwapped, RecipeRated |
| plan          | Plan (PlanDay, PlanMeal within)  | PlanCreated, PlanRecalibrated, PlanCompleted |
| tracking      | FoodLog, WaterLog, WeightLog, FastingSession, ProgressPhoto | FoodLogged, WaterLogged, WeightLogged, FastingStarted, FastingCompleted |
| grocery       | GroceryList (GroceryItem within) | GroceryGenerated |
| gamification  | Streak, Achievement              | DayCompleted, CelebrationTriggered, AchievementUnlocked, StreakBroken, LevelUp |
| coach         | CoachConversation (CoachMessage within) | MessageSent, MessageReceived, IntentDetected |
| vision        | VisionJob                        | VisionJobEnqueued, VisionJobCompleted, VisionJobFailed, FoodPhotoLogged |
| voice         | (stateless)                      | VoiceLogged |
| notifications | PushToken                        | PushQueued, PushDelivered |
| billing       | Subscription, Customer, Invoice  | TrialStarted, SubscriptionCreated, SubscriptionUpdated, SubscriptionCancelled, PaymentSucceeded, PaymentFailed |

## Glossary (canonical → display matrix)

Display strings live in `i18n_translations(scope, key, locale, value)`. The
table below shows canonical EN and Spanish for orientation; full 5-locale
coverage is in the seed script (`scripts/seed_i18n.py`).

### Allergens (14)
`dairy gluten tree_nuts peanuts shellfish fish egg soy sesame celery mustard
lupin sulphites molluscs`

### Conditions (25)
`diabetes_t1 diabetes_t2 hypertension dyslipidemia hypercholesterolemia
hypothyroidism hyperthyroidism ibs ibd celiac lactose_intolerance obesity
overweight pregnancy lactation athletic_load ckd ischemic_heart_disease
fatty_liver iron_deficiency_anemia pcos gout vitamin_d_deficiency
chronic_insomnia mild_depression`

### Goals (5)
`weight_loss maintain muscle_gain weight_gain health`

### Activity levels (5)
`sedentary lightly_active moderately_active very_active extra_active`

### Meal times (4)
`breakfast lunch dinner snack`

### Log methods (6)
`photo voice text barcode search manual`

### Plan statuses (5)
`active completed cancelled paused draft`

### Grocery categories (5)
`fruits_vegetables proteins dairy pantry other`

### Streak types (3 — schema-bounded)
`daily fasting protein`

### Achievement codes (32)
See `app.gamification.domain.catalog.CATALOG`. Seeded via migration 0005 and
mirrored into `achievements_catalog`. Includes streaks (3/7/14/30/100d),
fasting unlocks (16/18/20h + 7d streak), variety/breakfast/weekend badges,
first-action badges (meal/recipe-swap/grocery/coach/photo), and level badges
(level_5, level_10).

### Billing
- Plans: `free premium family`
- Providers: `stripe mercadopago`
- Statuses: `trialing active past_due cancelled incomplete`

## Cross-context integration

| Event source | Subscribed in |
|--------------|---------------|
| identity.UserRegistered      | nutrition (seed default goals), profile, billing (start trial) |
| tracking.WeightLogged        | nutrition (recalibration), gamification (streak/achievement) |
| tracking.FoodLogged          | gamification (daily_goals + achievements), tracking (cache invalidate), coach (proactive hint) |
| tracking.FastingCompleted    | gamification (streak + achievements) |
| vision.FoodPhotoLogged       | tracking (food_log insert), gamification (mark meal goal), coach (cross-check hint) |
| billing.SubscriptionCancelled| identity (entitlement downgrade) |

## Invariants

- **Macro tolerance**: any computed macro total within `MACRO_TOLERANCE=0.02`
  of the stored aggregate is considered consistent (ADR-0002).
- **Allergens**: hard-exclusion enforced via DB trigger AND application
  filter — never relaxed by ranking or LLM passes.
- **Idempotency**: every write endpoint accepts `Idempotency-Key` header;
  redis-cached for 24 h keyed by `(user, path, key)`.
- **Webhook events**: deduplicated via `webhook_events.event_id` UNIQUE.
- **EXIF strip**: any GPS or device tag surviving compression aborts the
  request (`EXIFLeakError`).
- **One active plan / fasting session** per user (UNIQUE partial indexes).
- **Cost cap**: ADR-0004 — $1.50/user/day OpenAI spend, breaker on each client.
