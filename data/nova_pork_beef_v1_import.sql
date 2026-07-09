DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '4df34ae8-7acc-4b81-8925-790dc77cdec1'::uuid,
    'Pork Loin with Beans, Egg and Corn Tortilla', '{"es": "Lomo de cerdo con frijoles, huevo y tortilla de ma\u00edz"}'::jsonb,
    'Desayuno alto en proteína con lomo de cerdo, frijoles negros y huevo sobre tortilla de maíz.', '{"es": "Desayuno alto en prote\u00edna con lomo de cerdo, frijoles negros y huevo sobre tortilla de ma\u00edz."}'::jsonb,
    442, 39, 35, 17, 6, 3, 390, 5,
    'breakfast'::meal_time_enum, 20,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 90g de lomo de cerdo con sal, pimienta y comino.", "Calienta una sart\u00e9n a fuego medio con 1 cdita de aceite; cocina el lomo 5 min por lado hasta dorar.", "En la misma sart\u00e9n, calienta 70g de frijoles negros cocidos con 50g de tomate picado y cebolla.", "Bate 1 huevo (50g) con pizca de sal y cocina revuelto 2 min en la sart\u00e9n.", "Calienta 1 tortilla de ma\u00edz (30g) en comal seco 1 min por lado.", "Sirve el lomo rebanado sobre la tortilla con frijoles y huevo encima."]'::jsonb))),
    '{"es": ["Sazona 90g de lomo de cerdo con sal, pimienta y comino.", "Calienta una sart\u00e9n a fuego medio con 1 cdita de aceite; cocina el lomo 5 min por lado hasta dorar.", "En la misma sart\u00e9n, calienta 70g de frijoles negros cocidos con 50g de tomate picado y cebolla.", "Bate 1 huevo (50g) con pizca de sal y cocina revuelto 2 min en la sart\u00e9n.", "Calienta 1 tortilla de ma\u00edz (30g) en comal seco 1 min por lado.", "Sirve el lomo rebanado sobre la tortilla con frijoles y huevo encima."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Beans, Egg and Corn Tortilla';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('29d83094-8b34-4ed9-bc57-40e4d8ddb2c7'::uuid, _rid, 'lomo de cerdo', 90, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c644a848-564d-4276-9612-e76544fa4074'::uuid, _rid, 'frijoles negros cocidos', 70, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1ccede77-992f-474a-b466-9f50542fff46'::uuid, _rid, 'huevo entero', 50, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('117ad050-31a4-4695-820d-9273b5f9b1a2'::uuid, _rid, 'tortilla de maíz', 30, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0a23d4e1-dacc-4198-9cf4-4a3f4557e702'::uuid, _rid, 'aceite de oliva', 3, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1a482042-02db-47e9-8cd6-9f6ea8debcfa'::uuid, _rid, 'tomate', 40, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c455592e-b0be-4c6d-8d66-25123230c4ff'::uuid, _rid, 'cebolla blanca', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '281bb986-a7ea-4941-8ff7-81a01890738d'::uuid,
    'Pork Chop with Rice, Zucchini and Egg', '{"es": "Chuleta de cerdo con arroz, calabacita y huevo"}'::jsonb,
    'Desayuno completo con chuleta de cerdo magra, arroz blanco y huevo revuelto.', '{"es": "Desayuno completo con chuleta de cerdo magra, arroz blanco y huevo revuelto."}'::jsonb,
    428, 34, 31, 15, 2, 3, 380, 4,
    'breakfast'::meal_time_enum, 22,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 90g de chuleta de cerdo con sal, ajo en polvo y p\u00e1prika.", "Cocina la chuleta en sart\u00e9n con 1 cdita de aceite a fuego medio, 5 min por lado.", "Cocina 80g de arroz blanco en 160ml de agua con sal por 18 min a fuego bajo.", "Saltea 100g de calabacita en cubos con el aceite restante 3 min hasta suavizar.", "Bate 1 huevo (50g) y cocina revuelto 2 min; mezcla con la calabacita.", "Sirve la chuleta con el arroz y la mezcla de huevo y calabacita."]'::jsonb))),
    '{"es": ["Sazona 90g de chuleta de cerdo con sal, ajo en polvo y p\u00e1prika.", "Cocina la chuleta en sart\u00e9n con 1 cdita de aceite a fuego medio, 5 min por lado.", "Cocina 80g de arroz blanco en 160ml de agua con sal por 18 min a fuego bajo.", "Saltea 100g de calabacita en cubos con el aceite restante 3 min hasta suavizar.", "Bate 1 huevo (50g) y cocina revuelto 2 min; mezcla con la calabacita.", "Sirve la chuleta con el arroz y la mezcla de huevo y calabacita."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Rice, Zucchini and Egg';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7637bc13-270b-460a-8f85-e43d8b5acf66'::uuid, _rid, 'chuleta de cerdo', 90, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('25e8f138-1eb5-4c10-a894-261c7c2ab397'::uuid, _rid, 'arroz blanco', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b409357a-737e-4621-a905-000f0d1151ae'::uuid, _rid, 'calabacita', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c0ab7f2b-3d1b-43c0-8840-33fd7bd831e1'::uuid, _rid, 'huevo entero', 50, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3dd63693-a5c7-4546-ae1b-3e2f9194e417'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c6422a9b-7ac0-44dd-988f-6c017023e500'::uuid, _rid, 'pimiento morrón', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('54273a0b-05be-445e-b453-b5cdb74528f8'::uuid, _rid, 'cebolla blanca', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '9643156f-71a4-49fd-af41-b77fd95e6967'::uuid,
    'Pork Leg with Sweet Potato and Broccoli', '{"es": "Pierna de cerdo con camote y br\u00f3coli"}'::jsonb,
    'Desayuno rico en potasio con pierna de cerdo magra, camote al horno y brócoli.', '{"es": "Desayuno rico en potasio con pierna de cerdo magra, camote al horno y br\u00f3coli."}'::jsonb,
    412, 36, 40, 13, 6, 5, 340, 4,
    'breakfast'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Precalienta el horno a 200\u00b0C. Sazona 110g de pierna de cerdo con sal, romero y ajo.", "Hornea la pierna en bandeja con 1 cdita de aceite por 25 min hasta cocci\u00f3n completa.", "Mientras, corta 150g de camote en cubos y cocina al vapor 15 min hasta suavizar.", "Blanquea 80g de br\u00f3coli en agua hirviendo con sal por 4 min; escurre.", "Machaca ligeramente el camote con una pizca de sal y pimienta.", "Sirve la pierna de cerdo con el camote y el br\u00f3coli al lado."]'::jsonb))),
    '{"es": ["Precalienta el horno a 200\u00b0C. Sazona 110g de pierna de cerdo con sal, romero y ajo.", "Hornea la pierna en bandeja con 1 cdita de aceite por 25 min hasta cocci\u00f3n completa.", "Mientras, corta 150g de camote en cubos y cocina al vapor 15 min hasta suavizar.", "Blanquea 80g de br\u00f3coli en agua hirviendo con sal por 4 min; escurre.", "Machaca ligeramente el camote con una pizca de sal y pimienta.", "Sirve la pierna de cerdo con el camote y el br\u00f3coli al lado."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Sweet Potato and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a3ee87d1-4938-4661-a657-3aec5bc212f8'::uuid, _rid, 'pierna de cerdo', 110, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2a9650be-da58-4e2e-9bee-bbcf61044927'::uuid, _rid, 'camote', 150, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('811ea700-b44f-4d85-a5c0-64a52c5319de'::uuid, _rid, 'brócoli', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('290b6b68-2b0f-47bb-bb36-f7cab430777a'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('13099c50-767a-42a2-a4d0-acc203af7736'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7953719a-c3a8-46ec-b51a-956efbbf2888'::uuid, _rid, 'tomate', 40, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '08183ecf-5053-4671-8224-b27529383cc7'::uuid,
    'Shredded Pork with Plantain and Corn Tortillas', '{"es": "Lomo de cerdo deshebrado con pl\u00e1tano y tortillas de ma\u00edz"}'::jsonb,
    'Desayuno energético con lomo de cerdo deshebrado, plátano maduro frito y tortillas.', '{"es": "Desayuno energ\u00e9tico con lomo de cerdo deshebrado, pl\u00e1tano maduro frito y tortillas."}'::jsonb,
    438, 32, 50, 14, 3, 8, 360, 4,
    'breakfast'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Cocina 100g de lomo de cerdo en agua con sal, ajo y comino a fuego medio 20 min.", "Retira el lomo, deja enfriar 5 min y deshebra con dos tenedores.", "Calienta 1 cdita de aceite en sart\u00e9n; sofr\u00ede el lomo deshebrado 3 min hasta dorar.", "En otra sart\u00e9n con aceite m\u00ednimo, dora 80g de pl\u00e1tano maduro cortado en rodajas 2 min por lado.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Sirve el cerdo deshebrado sobre tortillas con el pl\u00e1tano y cebolla morada al gusto."]'::jsonb))),
    '{"es": ["Cocina 100g de lomo de cerdo en agua con sal, ajo y comino a fuego medio 20 min.", "Retira el lomo, deja enfriar 5 min y deshebra con dos tenedores.", "Calienta 1 cdita de aceite en sart\u00e9n; sofr\u00ede el lomo deshebrado 3 min hasta dorar.", "En otra sart\u00e9n con aceite m\u00ednimo, dora 80g de pl\u00e1tano maduro cortado en rodajas 2 min por lado.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Sirve el cerdo deshebrado sobre tortillas con el pl\u00e1tano y cebolla morada al gusto."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Shredded Pork with Plantain and Corn Tortillas';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f5e20f12-66fc-4bbd-982c-1cc9d4c93c30'::uuid, _rid, 'lomo de cerdo', 100, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8024b123-0e64-4ce7-85ba-96b007b4b4b6'::uuid, _rid, 'plátano maduro', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8312ae1a-dbed-4dda-b48f-ddf92ba01440'::uuid, _rid, 'tortilla de maíz', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5c42609e-c08a-4666-b315-7588989e8cda'::uuid, _rid, 'aceite de oliva', 3, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3ce0620a-3b1c-4af4-aa43-0694aca91f5c'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('558c5300-b241-4a5c-93f3-c1d946e2bbb1'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '9418d869-5275-4ecb-8d4e-dbfd82e877ef'::uuid,
    'Pork Loin with Yuca and Carrot', '{"es": "Lomo de cerdo con yuca y zanahoria"}'::jsonb,
    'Desayuno con lomo de cerdo, yuca cocida y zanahoria salteada.', '{"es": "Desayuno con lomo de cerdo, yuca cocida y zanahoria salteada."}'::jsonb,
    408, 32, 39, 14, 2, 4, 350, 4,
    'breakfast'::meal_time_enum, 20,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 110g de lomo de cerdo con sal, comino y ajo molido.", "Cocina en sart\u00e9n con 1 cdita de aceite a fuego medio, 6 min por lado.", "Pela y trocea 80g de yuca; hierve en agua con sal 20 min hasta suavizar.", "Saltea 60g de zanahoria en rodajas con ajo picado en el aceite restante, 5 min.", "Escurre la yuca; aplana ligeramente con tenedor, espolvorea sal y ceboll\u00edn.", "Sirve el lomo rebanado con la yuca y la zanahoria salteada."]'::jsonb))),
    '{"es": ["Sazona 110g de lomo de cerdo con sal, comino y ajo molido.", "Cocina en sart\u00e9n con 1 cdita de aceite a fuego medio, 6 min por lado.", "Pela y trocea 80g de yuca; hierve en agua con sal 20 min hasta suavizar.", "Saltea 60g de zanahoria en rodajas con ajo picado en el aceite restante, 5 min.", "Escurre la yuca; aplana ligeramente con tenedor, espolvorea sal y ceboll\u00edn.", "Sirve el lomo rebanado con la yuca y la zanahoria salteada."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Yuca and Carrot';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c87c8fcf-d3e6-4493-a8f5-72bb1fcff268'::uuid, _rid, 'lomo de cerdo', 110, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e0cc58ac-e1aa-414c-a5e4-296f5ac22b2e'::uuid, _rid, 'yuca', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bf4c65e8-c5a5-46b8-89ae-938e65cd2dc2'::uuid, _rid, 'zanahoria', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bc02cd74-f527-43da-9083-0a71fab361ef'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('eee9fbd2-f51c-4d5b-b228-90a1c696ff92'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0ed98600-d6ca-4f99-8e0d-f86cecc51a4d'::uuid, _rid, 'cebolla blanca', 25, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '6cd7bf8f-5fdb-434b-9a8d-9cefa38e4e99'::uuid,
    'Pork Chop with Black Beans and Scrambled Egg', '{"es": "Chuleta de cerdo con frijoles negros y huevo revuelto"}'::jsonb,
    'Desayuno proteico con chuleta de cerdo, frijoles negros y huevo revuelto.', '{"es": "Desayuno proteico con chuleta de cerdo, frijoles negros y huevo revuelto."}'::jsonb,
    399, 38, 24, 17, 7, 2, 400, 5,
    'breakfast'::meal_time_enum, 20,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 90g de chuleta de cerdo con sal, pimienta y or\u00e9gano.", "Cocina en sart\u00e9n a fuego medio con 1 cdita de aceite, 5 min por lado.", "Calienta 80g de frijoles negros cocidos con 40g de tomate picado y pizca de comino, 3 min.", "Bate 1 huevo (50g) con sal y cocina revuelto en la misma sart\u00e9n 2 min.", "Mezcla el huevo revuelto con los frijoles calientes.", "Sirve la chuleta de cerdo acompa\u00f1ada de la mezcla de frijoles y huevo."]'::jsonb))),
    '{"es": ["Sazona 90g de chuleta de cerdo con sal, pimienta y or\u00e9gano.", "Cocina en sart\u00e9n a fuego medio con 1 cdita de aceite, 5 min por lado.", "Calienta 80g de frijoles negros cocidos con 40g de tomate picado y pizca de comino, 3 min.", "Bate 1 huevo (50g) con sal y cocina revuelto en la misma sart\u00e9n 2 min.", "Mezcla el huevo revuelto con los frijoles calientes.", "Sirve la chuleta de cerdo acompa\u00f1ada de la mezcla de frijoles y huevo."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Black Beans and Scrambled Egg';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a0eea90c-386e-43e3-bbc7-5fb61ba1cee7'::uuid, _rid, 'chuleta de cerdo', 90, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('87003412-9180-432c-9846-e6e18b03a247'::uuid, _rid, 'frijoles negros cocidos', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('700da323-8452-4336-9eaa-e53c40dabe9c'::uuid, _rid, 'huevo entero', 50, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('34ca35fb-c781-4670-8c56-5af282c9a212'::uuid, _rid, 'aceite de oliva', 3, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ae1c0ce7-cdc6-4dfe-a64d-ecd8ab6fcfe1'::uuid, _rid, 'tomate', 40, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9fb44aec-6e5a-42e2-9930-595c4c505c70'::uuid, _rid, 'cebolla blanca', 30, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'a127e991-a2df-4c7b-ac56-c428b8a99f0e'::uuid,
    'Pork Leg with Brown Rice, Spinach and Egg', '{"es": "Pierna de cerdo con arroz integral, espinacas y huevo"}'::jsonb,
    'Desayuno completo con pierna de cerdo, arroz integral, espinacas y huevo.', '{"es": "Desayuno completo con pierna de cerdo, arroz integral, espinacas y huevo."}'::jsonb,
    427, 42, 24, 18, 4, 2, 360, 5,
    'breakfast'::meal_time_enum, 20,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Cocina 80g de arroz integral en 180ml de agua con sal a fuego bajo, 30 min.", "Sazona 110g de pierna de cerdo con sal, ajo y p\u00e1prika; cocina en sart\u00e9n 5 min por lado.", "Saltea 80g de espinacas con 1 diente de ajo picado en sart\u00e9n con aceite, 2 min.", "Bate 1 huevo (50g) y cocina revuelto con las espinacas, 2 min m\u00e1s.", "Calienta el arroz integral cocido con pizca de sal.", "Sirve la pierna de cerdo con el arroz y la mezcla de espinaca y huevo."]'::jsonb))),
    '{"es": ["Cocina 80g de arroz integral en 180ml de agua con sal a fuego bajo, 30 min.", "Sazona 110g de pierna de cerdo con sal, ajo y p\u00e1prika; cocina en sart\u00e9n 5 min por lado.", "Saltea 80g de espinacas con 1 diente de ajo picado en sart\u00e9n con aceite, 2 min.", "Bate 1 huevo (50g) y cocina revuelto con las espinacas, 2 min m\u00e1s.", "Calienta el arroz integral cocido con pizca de sal.", "Sirve la pierna de cerdo con el arroz y la mezcla de espinaca y huevo."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Brown Rice, Spinach and Egg';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4c0e8e46-3a94-4bdc-8931-d612728d6719'::uuid, _rid, 'pierna de cerdo', 110, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7b624912-f2e7-4aab-98fb-da7b89b58cdd'::uuid, _rid, 'arroz integral', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4f305863-1121-46db-bbb5-96770dd5e478'::uuid, _rid, 'espinacas', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('19db1c30-eb4b-4088-b256-d0ffb79b079a'::uuid, _rid, 'huevo entero', 50, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4470d5c4-98aa-4ca2-b70c-93ad1a37e5fb'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7e6dd8ca-8441-4ba6-9102-b770e5b859f4'::uuid, _rid, 'ajo', 5, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5e0f8901-1d6d-4665-837a-423a799793f3'::uuid, _rid, 'tomate', 50, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'f27585d4-a05e-4ae8-9f46-5c1e053ae797'::uuid,
    'Pork Loin with Cactus and Egg in Corn Tortilla', '{"es": "Lomo de cerdo con nopales y huevo en tortilla de ma\u00edz"}'::jsonb,
    'Desayuno mexicano con lomo de cerdo, nopales y huevo sobre tortilla.', '{"es": "Desayuno mexicano con lomo de cerdo, nopales y huevo sobre tortilla."}'::jsonb,
    391, 37, 23, 18, 4, 3, 370, 5,
    'breakfast'::meal_time_enum, 20,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 100g de lomo de cerdo con sal, comino y chile en polvo.", "Cocina en sart\u00e9n con aceite a fuego medio, 5 min por lado; rebana.", "Lava y trocea 100g de nopales; cocina en sart\u00e9n seca con sal 5 min hasta que pierdan baba.", "Agrega los nopales al cerdo, a\u00f1ade 1 huevo (50g) batido y revuelve 2 min.", "Calienta 1 tortilla de ma\u00edz (30g) en comal seco 1 min por lado.", "Sirve la mezcla de cerdo, nopales y huevo sobre la tortilla con salsa al gusto."]'::jsonb))),
    '{"es": ["Sazona 100g de lomo de cerdo con sal, comino y chile en polvo.", "Cocina en sart\u00e9n con aceite a fuego medio, 5 min por lado; rebana.", "Lava y trocea 100g de nopales; cocina en sart\u00e9n seca con sal 5 min hasta que pierdan baba.", "Agrega los nopales al cerdo, a\u00f1ade 1 huevo (50g) batido y revuelve 2 min.", "Calienta 1 tortilla de ma\u00edz (30g) en comal seco 1 min por lado.", "Sirve la mezcla de cerdo, nopales y huevo sobre la tortilla con salsa al gusto."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Cactus and Egg in Corn Tortilla';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('43157f72-af05-4fc5-b5db-209ae92178f7'::uuid, _rid, 'lomo de cerdo', 100, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('04bcef41-a4aa-406f-92bb-271570e09a32'::uuid, _rid, 'nopales', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('83c93e2b-dd80-4743-b7f7-da64aac314e8'::uuid, _rid, 'huevo entero', 50, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('11130f33-65cc-453b-80d5-19098a428625'::uuid, _rid, 'tortilla de maíz', 30, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('573de61e-4569-40d6-9b64-74536fb2204e'::uuid, _rid, 'aceite de oliva', 3, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ada3c99b-140a-4bf0-95a6-99f5e5356edf'::uuid, _rid, 'tomate', 40, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('224cb5a6-232d-4706-aa62-52220f932a45'::uuid, _rid, 'cebolla blanca', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '3598bd3c-f50e-4e8b-a72e-cf3f68f8491d'::uuid,
    'Roasted Pork Loin with Rice and Broccoli', '{"es": "Lomo de cerdo al horno con arroz y br\u00f3coli"}'::jsonb,
    'Almuerzo alto en proteína con lomo de cerdo al horno, arroz blanco y brócoli al vapor.', '{"es": "Almuerzo alto en prote\u00edna con lomo de cerdo al horno, arroz blanco y br\u00f3coli al vapor."}'::jsonb,
    554, 51, 43, 20, 4, 3, 420, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Precalienta horno a 200\u00b0C. Sazona 165g de lomo de cerdo con sal, ajo, romero y aceite.", "Hornea el lomo en bandeja 25-30 min hasta que la temperatura interna llegue a 70\u00b0C.", "Cocina 110g de arroz blanco en 220ml de agua con sal por 18 min a fuego bajo.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal por 4 min; escurre y reserva.", "Deja reposar el lomo 5 min; rebana en medallones.", "Sirve el lomo sobre el arroz con el br\u00f3coli al lado y jugo de lim\u00f3n al gusto."]'::jsonb))),
    '{"es": ["Precalienta horno a 200\u00b0C. Sazona 165g de lomo de cerdo con sal, ajo, romero y aceite.", "Hornea el lomo en bandeja 25-30 min hasta que la temperatura interna llegue a 70\u00b0C.", "Cocina 110g de arroz blanco en 220ml de agua con sal por 18 min a fuego bajo.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal por 4 min; escurre y reserva.", "Deja reposar el lomo 5 min; rebana en medallones.", "Sirve el lomo sobre el arroz con el br\u00f3coli al lado y jugo de lim\u00f3n al gusto."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Roasted Pork Loin with Rice and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8f7d8781-b537-4e0f-8b7b-1242169da720'::uuid, _rid, 'lomo de cerdo', 165, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ed354409-cd5d-4534-bd28-be5eb957caee'::uuid, _rid, 'arroz blanco', 110, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3f936940-19d0-4ad1-84b9-aa3bbfad751a'::uuid, _rid, 'brócoli', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('02941cb5-d4cc-4f5b-8f36-59b5307a28ff'::uuid, _rid, 'aceite de oliva', 5, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('19244703-d269-4268-aff3-b31ab40b2a7a'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a8c4b572-a8d7-43c7-8274-7b21cc47b415'::uuid, _rid, 'tomate', 40, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1bb42846-1697-4963-9ac8-0fb5c0194c78'::uuid, _rid, 'cebolla blanca', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '05a37fac-8f99-420a-84a2-d7c701d9a3b8'::uuid,
    'Pork Chop with Black Beans and Brown Rice', '{"es": "Chuleta de cerdo con frijoles negros y arroz integral"}'::jsonb,
    'Almuerzo completo con chuleta de cerdo, frijoles negros y arroz integral.', '{"es": "Almuerzo completo con chuleta de cerdo, frijoles negros y arroz integral."}'::jsonb,
    596, 53, 47, 21, 10, 3, 450, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 160g de chuleta de cerdo con sal, comino, ajo y p\u00e1prika.", "Cocina en sart\u00e9n con aceite a fuego medio-alto, 6 min por lado hasta dorar.", "Cocina 80g de arroz integral en 180ml de agua con sal 30 min a fuego bajo.", "Calienta 100g de frijoles negros con 50g de tomate picado, cebolla y comino, 5 min.", "Sofr\u00ede 70g de cebolla y tomate picados en el aceite restante 3 min.", "Sirve la chuleta con el arroz integral y los frijoles calientes."]'::jsonb))),
    '{"es": ["Sazona 160g de chuleta de cerdo con sal, comino, ajo y p\u00e1prika.", "Cocina en sart\u00e9n con aceite a fuego medio-alto, 6 min por lado hasta dorar.", "Cocina 80g de arroz integral en 180ml de agua con sal 30 min a fuego bajo.", "Calienta 100g de frijoles negros con 50g de tomate picado, cebolla y comino, 5 min.", "Sofr\u00ede 70g de cebolla y tomate picados en el aceite restante 3 min.", "Sirve la chuleta con el arroz integral y los frijoles calientes."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Black Beans and Brown Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9aa5d268-bb8f-4df8-ab17-03c9c6825f00'::uuid, _rid, 'chuleta de cerdo', 160, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('02bc8522-f113-43a5-be90-705bbc79294f'::uuid, _rid, 'frijoles negros cocidos', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3fd49862-3f85-4ced-bc82-71af8bd18a11'::uuid, _rid, 'arroz integral', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ef9e044d-3aef-48d1-8cee-1be3c395937c'::uuid, _rid, 'aceite de oliva', 5, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e3eed23d-2468-4a6d-88d3-06cfce3208d0'::uuid, _rid, 'tomate', 50, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a0b1da0c-8ca4-45d5-ac9c-b23a832cbfbe'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'a4376c54-69e2-4a37-999c-cbb1c6852834'::uuid,
    'Pork Loin with Lentils and Carrot', '{"es": "Lomo de cerdo con lentejas y zanahoria"}'::jsonb,
    'Almuerzo con lomo de cerdo, lentejas cocidas y zanahoria.', '{"es": "Almuerzo con lomo de cerdo, lentejas cocidas y zanahoria."}'::jsonb,
    631, 57, 56, 19, 10, 4, 430, 5,
    'lunch'::meal_time_enum, 35,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 160g de lomo de cerdo con sal, comino y ajo; dora en sart\u00e9n con aceite 5 min por lado.", "Cocina 120g de lentejas en agua con sal, hoja de laurel y ajo por 20 min hasta tiernas.", "Sofr\u00ede 80g de zanahoria en rodajas con cebolla y ajo en aceite, 5 min.", "Agrega las lentejas a la sart\u00e9n con zanahoria, mezcla bien y calienta 3 min.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min a fuego bajo.", "Sirve el lomo rebanado con las lentejas, zanahoria y arroz."]'::jsonb))),
    '{"es": ["Sazona 160g de lomo de cerdo con sal, comino y ajo; dora en sart\u00e9n con aceite 5 min por lado.", "Cocina 120g de lentejas en agua con sal, hoja de laurel y ajo por 20 min hasta tiernas.", "Sofr\u00ede 80g de zanahoria en rodajas con cebolla y ajo en aceite, 5 min.", "Agrega las lentejas a la sart\u00e9n con zanahoria, mezcla bien y calienta 3 min.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min a fuego bajo.", "Sirve el lomo rebanado con las lentejas, zanahoria y arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Lentils and Carrot';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0376b3c5-f3c8-4d0f-9082-af5903c757d7'::uuid, _rid, 'lomo de cerdo', 160, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ec69d57b-911d-4b8e-9160-efbc03f064f8'::uuid, _rid, 'lentejas cocidas', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b13b69ff-e5ca-44ee-a136-9a66d81a0237'::uuid, _rid, 'zanahoria', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c4539908-b631-4a1d-85c3-8721104045ab'::uuid, _rid, 'arroz blanco', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e84160bb-1392-4b9e-995f-fd3c7bd30fb1'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bf483e72-fb04-4da1-b86c-09340c16676b'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6e57509e-d864-4296-8a34-29ad635a5f72'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '8079b47f-e314-4368-ad22-cecf1827821e'::uuid,
    'Pork Leg with Chickpeas and Rice', '{"es": "Pierna de cerdo con garbanzos y arroz"}'::jsonb,
    'Almuerzo nutritivo con pierna de cerdo, garbanzos y arroz blanco.', '{"es": "Almuerzo nutritivo con pierna de cerdo, garbanzos y arroz blanco."}'::jsonb,
    627, 55, 56, 19, 8, 3, 440, 5,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 155g de pierna de cerdo con sal, p\u00e1prika, ajo y comino.", "Cocina en sart\u00e9n con aceite a fuego medio, 6 min por lado.", "Sofr\u00ede 70g de pimiento y cebolla picados en aceite 3 min; agrega 100g de garbanzos cocidos.", "A\u00f1ade 50g de tomate picado y especias al gusto; cocina 5 min hasta integrar.", "Cocina 80g de arroz blanco en agua con sal, 18 min.", "Sirve la pierna con los garbanzos guisados y el arroz."]'::jsonb))),
    '{"es": ["Sazona 155g de pierna de cerdo con sal, p\u00e1prika, ajo y comino.", "Cocina en sart\u00e9n con aceite a fuego medio, 6 min por lado.", "Sofr\u00ede 70g de pimiento y cebolla picados en aceite 3 min; agrega 100g de garbanzos cocidos.", "A\u00f1ade 50g de tomate picado y especias al gusto; cocina 5 min hasta integrar.", "Cocina 80g de arroz blanco en agua con sal, 18 min.", "Sirve la pierna con los garbanzos guisados y el arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Chickpeas and Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7750e315-6c40-4207-8d63-dc1067e50508'::uuid, _rid, 'pierna de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6b54665b-beed-4eb0-8ad7-b5eca189a789'::uuid, _rid, 'garbanzos cocidos', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('df9fb958-1cdc-4895-a304-1c77959c4dc0'::uuid, _rid, 'arroz blanco', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e22c8f08-e0d4-4b6e-bc28-f8218b271a82'::uuid, _rid, 'aceite de oliva', 5, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9d9549e4-2834-434a-a2e3-da5ba8ed9fec'::uuid, _rid, 'pimiento morrón', 40, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('dd7c685b-199b-4bc8-9fed-028f0f67323d'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1e5c49e5-d592-47ce-b383-f529627f212f'::uuid, _rid, 'tomate', 50, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '7d1d7f74-2d56-4d25-90d7-435b2a05ffcc'::uuid,
    'Pork Loin in Tomato Sauce with Quinoa and Sweet Potato', '{"es": "Lomo de cerdo en salsa de tomate con quinoa y camote"}'::jsonb,
    'Almuerzo con lomo de cerdo en salsa de tomate natural, quinoa y camote.', '{"es": "Almuerzo con lomo de cerdo en salsa de tomate natural, quinoa y camote."}'::jsonb,
    615, 51, 56, 21, 5, 8, 460, 6,
    'lunch'::meal_time_enum, 35,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 155g de lomo de cerdo en sart\u00e9n con aceite a fuego alto, 3 min por lado.", "Agrega 150g de tomate triturado, cebolla picada, ajo y or\u00e9gano; cocina 15 min a fuego medio.", "Cocina 120g de quinoa en 240ml de agua con sal, 15 min a fuego bajo; esponja con tenedor.", "Hierve 100g de camote en cubos en agua con sal, 15 min hasta suavizar.", "Escurre el camote; sazona con sal y pizca de canela.", "Sirve el lomo en salsa de tomate sobre la quinoa con el camote al lado."]'::jsonb))),
    '{"es": ["Dora 155g de lomo de cerdo en sart\u00e9n con aceite a fuego alto, 3 min por lado.", "Agrega 150g de tomate triturado, cebolla picada, ajo y or\u00e9gano; cocina 15 min a fuego medio.", "Cocina 120g de quinoa en 240ml de agua con sal, 15 min a fuego bajo; esponja con tenedor.", "Hierve 100g de camote en cubos en agua con sal, 15 min hasta suavizar.", "Escurre el camote; sazona con sal y pizca de canela.", "Sirve el lomo en salsa de tomate sobre la quinoa con el camote al lado."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin in Tomato Sauce with Quinoa and Sweet Potato';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9fb66dc1-f4e8-4b00-8a5c-77836fc074f1'::uuid, _rid, 'lomo de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('cad15124-257c-498b-a1b6-969ba2f38ad2'::uuid, _rid, 'quinoa', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('90b61935-b869-448a-8f47-ecbed73b789a'::uuid, _rid, 'camote', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f0fd90c8-ddeb-4a18-9834-9706136c35f2'::uuid, _rid, 'tomate triturado', 150, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3264ebc0-5ed0-4561-a0df-2a27ebcca94d'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a3dab8b2-2a5f-484b-b8cf-df561b092d00'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('95fad640-6fc6-4c10-94c8-83c7d650f058'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '9e2c97c9-8e95-4b02-9d7b-3539a4b1dc31'::uuid,
    'Pork Chop with Potato, Green Beans and Rice', '{"es": "Chuleta de cerdo al lim\u00f3n con papa, ejotes y arroz"}'::jsonb,
    'Chuleta de cerdo al limón con papa, ejotes tiernos y arroz blanco.', '{"es": "Chuleta de cerdo al lim\u00f3n con papa, ejotes tiernos y arroz blanco."}'::jsonb,
    588, 47, 55, 20, 4, 3, 410, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Marina 155g de chuleta de cerdo con jugo de 1 lim\u00f3n, sal, ajo y or\u00e9gano 10 min.", "Cocina la chuleta en sart\u00e9n con aceite a fuego medio, 6 min por lado.", "Hierve 140g de papa en cubos en agua con sal, 15 min; escurre.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min; escurre.", "Cocina 60g de arroz blanco en 120ml de agua con sal, 18 min.", "Sirve la chuleta con la papa, los ejotes y el arroz; exprime lim\u00f3n al gusto."]'::jsonb))),
    '{"es": ["Marina 155g de chuleta de cerdo con jugo de 1 lim\u00f3n, sal, ajo y or\u00e9gano 10 min.", "Cocina la chuleta en sart\u00e9n con aceite a fuego medio, 6 min por lado.", "Hierve 140g de papa en cubos en agua con sal, 15 min; escurre.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min; escurre.", "Cocina 60g de arroz blanco en 120ml de agua con sal, 18 min.", "Sirve la chuleta con la papa, los ejotes y el arroz; exprime lim\u00f3n al gusto."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Potato, Green Beans and Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2ad799d2-a225-428c-b6d1-0b0ee7301727'::uuid, _rid, 'chuleta de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2f713513-0382-4a70-a4e3-a7dc92fee04f'::uuid, _rid, 'papa', 140, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('58b7de2b-7bb1-4dfc-9b24-764abdd3dc34'::uuid, _rid, 'ejotes', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('93dd27a5-82c2-443e-95e1-2a4488b22f10'::uuid, _rid, 'arroz blanco', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e66b247b-08b2-429c-abaf-002ed8f47e56'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6de44603-430c-43d1-89a5-e56c8f57f8e9'::uuid, _rid, 'limón', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('27f08345-f70d-46fe-8490-be03e65dd53f'::uuid, _rid, 'cebolla blanca', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'f9dbdf5c-9481-4b17-9423-ea36e308d5ef'::uuid,
    'Pork Loin with Corn, Zucchini and Rice', '{"es": "Lomo de cerdo con ma\u00edz, calabacita y arroz"}'::jsonb,
    'Almuerzo colorido con lomo de cerdo, maíz tierno, calabacita y arroz.', '{"es": "Almuerzo colorido con lomo de cerdo, ma\u00edz tierno, calabacita y arroz."}'::jsonb,
    603, 52, 53, 21, 3, 5, 420, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 165g de lomo de cerdo con sal, comino y ajo; cocina en sart\u00e9n con aceite 6 min por lado.", "Saltea 100g de ma\u00edz tierno cocido y 100g de calabacita en cubos en el aceite restante, 5 min.", "Agrega 50g de tomate picado, sal y pimienta; saltea 2 min m\u00e1s.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min a fuego bajo.", "Rebana el lomo de cerdo en medallones.", "Sirve el lomo sobre el arroz con la mezcla de ma\u00edz y calabacita encima."]'::jsonb))),
    '{"es": ["Sazona 165g de lomo de cerdo con sal, comino y ajo; cocina en sart\u00e9n con aceite 6 min por lado.", "Saltea 100g de ma\u00edz tierno cocido y 100g de calabacita en cubos en el aceite restante, 5 min.", "Agrega 50g de tomate picado, sal y pimienta; saltea 2 min m\u00e1s.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min a fuego bajo.", "Rebana el lomo de cerdo en medallones.", "Sirve el lomo sobre el arroz con la mezcla de ma\u00edz y calabacita encima."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Corn, Zucchini and Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6e6e870f-25f7-4921-9d3b-c9f127937aa5'::uuid, _rid, 'lomo de cerdo', 165, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9792a460-37fb-49b8-abc0-86c25edf82c9'::uuid, _rid, 'maíz tierno', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e04032a4-256b-4305-93c0-1f3e39ff8eb2'::uuid, _rid, 'calabacita', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('dfa1696f-eadf-41b1-be52-c4d0b95fed86'::uuid, _rid, 'arroz blanco', 90, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('58931b97-2518-40db-920f-6eb20e1c627f'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bc9a72d3-b8a4-412d-82b3-8945e4638e72'::uuid, _rid, 'tomate', 50, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('67f774c2-b56b-4826-86a5-a45019672a3d'::uuid, _rid, 'cebolla blanca', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '22df89ec-9dcc-49b8-b704-556454bc194e'::uuid,
    'Pork Leg in Green Sauce with Rice and Chickpeas', '{"es": "Pierna de cerdo en salsa verde con arroz y garbanzos"}'::jsonb,
    'Pierna de cerdo guisada en salsa verde de tomate, arroz y garbanzos.', '{"es": "Pierna de cerdo guisada en salsa verde de tomate, arroz y garbanzos."}'::jsonb,
    612, 55, 54, 18, 6, 4, 450, 5,
    'lunch'::meal_time_enum, 35,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Cocina 160g de pierna de cerdo en agua con sal, ajo y cebolla 20 min; deshebra.", "Lic\u00faa 150g de tomate verde, 1 chile serrano, cebolla y cilantro para la salsa verde.", "Fr\u00ede la salsa verde en sart\u00e9n con aceite 5 min a fuego medio; agrega el cerdo deshebrado.", "Incorpora 60g de garbanzos cocidos a la salsa; cocina 5 min m\u00e1s.", "Cocina 100g de arroz blanco en 200ml de agua con sal, 18 min.", "Sirve el cerdo en salsa verde sobre el arroz con cilantro picado."]'::jsonb))),
    '{"es": ["Cocina 160g de pierna de cerdo en agua con sal, ajo y cebolla 20 min; deshebra.", "Lic\u00faa 150g de tomate verde, 1 chile serrano, cebolla y cilantro para la salsa verde.", "Fr\u00ede la salsa verde en sart\u00e9n con aceite 5 min a fuego medio; agrega el cerdo deshebrado.", "Incorpora 60g de garbanzos cocidos a la salsa; cocina 5 min m\u00e1s.", "Cocina 100g de arroz blanco en 200ml de agua con sal, 18 min.", "Sirve el cerdo en salsa verde sobre el arroz con cilantro picado."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg in Green Sauce with Rice and Chickpeas';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5e157fa6-fd5d-4888-8d81-16d3701be66f'::uuid, _rid, 'pierna de cerdo', 160, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a31ffb61-c4bc-4e56-bcd4-69dd82d51481'::uuid, _rid, 'garbanzos cocidos', 60, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7a6c68a7-c6c2-4eaa-8d4b-9c3ab8b78e77'::uuid, _rid, 'arroz blanco', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('eebeb06c-982a-4b30-9500-2cb67247840b'::uuid, _rid, 'tomate verde (tomatillo)', 150, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('aedb4e17-22e6-40e4-9d64-faa371cecee2'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c1c521bb-70de-41d2-b94f-c66021214fbc'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c5d9c417-5329-4c36-aab2-9556913c5149'::uuid, _rid, 'cilantro', 10, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'aa35dcec-0cc5-4bc2-b9eb-66388457ebaa'::uuid,
    'Pork Loin with Black Beans and Corn Tortillas', '{"es": "Lomo de cerdo con frijoles negros y tortillas de ma\u00edz"}'::jsonb,
    'Almuerzo tradicional con lomo de cerdo deshebrado, frijoles y tortillas.', '{"es": "Almuerzo tradicional con lomo de cerdo deshebrado, frijoles y tortillas."}'::jsonb,
    600, 54, 56, 20, 9, 3, 430, 6,
    'lunch'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 150g de lomo de cerdo; cocina en sart\u00e9n con aceite 6 min por lado; deshebra.", "Calienta 100g de frijoles negros con ajo, cebolla y comino en sart\u00e9n, 5 min.", "Calienta 2 tortillas de ma\u00edz (60g total) en comal seco 1 min por lado.", "Sofr\u00ede 70g de tomate y cebolla picados con el aceite restante, 3 min.", "Mezcla el cerdo deshebrado con el sofrito de tomate; sazona al gusto.", "Sirve el cerdo sobre las tortillas con los frijoles y salsa picante al gusto."]'::jsonb))),
    '{"es": ["Sazona 150g de lomo de cerdo; cocina en sart\u00e9n con aceite 6 min por lado; deshebra.", "Calienta 100g de frijoles negros con ajo, cebolla y comino en sart\u00e9n, 5 min.", "Calienta 2 tortillas de ma\u00edz (60g total) en comal seco 1 min por lado.", "Sofr\u00ede 70g de tomate y cebolla picados con el aceite restante, 3 min.", "Mezcla el cerdo deshebrado con el sofrito de tomate; sazona al gusto.", "Sirve el cerdo sobre las tortillas con los frijoles y salsa picante al gusto."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Black Beans and Corn Tortillas';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('cc7b172d-c3d2-420f-8e74-c37bd0107f6c'::uuid, _rid, 'lomo de cerdo', 150, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('02dbe58c-b68c-48fe-97bd-00e20b1966b7'::uuid, _rid, 'frijoles negros cocidos', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b3376c85-8cc1-4572-9c23-9159cb122cac'::uuid, _rid, 'tortilla de maíz', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('968a994a-1851-4876-943e-5ceba9a4f1e4'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('30d623e3-1f4a-408d-9a51-fd5e6a5c522a'::uuid, _rid, 'tomate', 50, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('33cd26ec-a7c0-40d0-bc21-4056d58d7258'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '7b00080b-7973-45e6-8ed1-8c11025c0da4'::uuid,
    'Pork Chop with Quinoa, Spinach and Lentils', '{"es": "Chuleta de cerdo con quinoa, espinacas y lentejas"}'::jsonb,
    'Almuerzo con chuleta de cerdo, quinoa, espinacas y lentejas.', '{"es": "Almuerzo con chuleta de cerdo, quinoa, espinacas y lentejas."}'::jsonb,
    582, 51, 47, 21, 11, 3, 420, 6,
    'lunch'::meal_time_enum, 35,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de chuleta de cerdo con sal, comino y p\u00e1prika; cocina en sart\u00e9n 5 min por lado.", "Cocina 120g de quinoa en 240ml de agua con sal, 15 min; esponja con tenedor.", "Hierve 70g de lentejas en agua con sal y laurel, 20 min hasta tiernas.", "Saltea 100g de espinacas con ajo picado en aceite, 2 min hasta marchitar.", "Mezcla la quinoa con las lentejas; sazona con sal, lim\u00f3n y comino.", "Sirve la chuleta con la mezcla de quinoa-lentejas y espinacas encima."]'::jsonb))),
    '{"es": ["Sazona 140g de chuleta de cerdo con sal, comino y p\u00e1prika; cocina en sart\u00e9n 5 min por lado.", "Cocina 120g de quinoa en 240ml de agua con sal, 15 min; esponja con tenedor.", "Hierve 70g de lentejas en agua con sal y laurel, 20 min hasta tiernas.", "Saltea 100g de espinacas con ajo picado en aceite, 2 min hasta marchitar.", "Mezcla la quinoa con las lentejas; sazona con sal, lim\u00f3n y comino.", "Sirve la chuleta con la mezcla de quinoa-lentejas y espinacas encima."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Quinoa, Spinach and Lentils';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bec08f99-c3d8-41b6-9bb8-2e8981853fb4'::uuid, _rid, 'chuleta de cerdo', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('315d52fb-b5ba-4847-bc04-22ff31514169'::uuid, _rid, 'quinoa', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a6337a5a-114d-4f6a-97dd-de1f8e011e79'::uuid, _rid, 'espinacas', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('48c13153-5093-4fa9-a8e6-c3f33d08382f'::uuid, _rid, 'lentejas cocidas', 70, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('663a20a4-2ed7-4b7c-9a3e-a932d9412430'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b3d9ee41-8dd9-4fbc-94a1-a3cfc174bd63'::uuid, _rid, 'limón', 20, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2f30d175-8a3d-45ce-a64d-e1d1a394c7bb'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'cca0a881-cd9b-4e83-898d-4e92e5999073'::uuid,
    'Pork Leg with Rice, Chayote and Green Beans', '{"es": "Pierna de cerdo con arroz, chayote y ejotes"}'::jsonb,
    'Almuerzo ligero con pierna de cerdo, arroz, chayote y ejotes.', '{"es": "Almuerzo ligero con pierna de cerdo, arroz, chayote y ejotes."}'::jsonb,
    585, 52, 52, 17, 5, 3, 410, 5,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 165g de pierna de cerdo con sal, ajo y or\u00e9gano; cocina en sart\u00e9n 6 min por lado.", "Cocina 130g de arroz blanco en 260ml de agua con sal, 18 min.", "Corta 100g de chayote en cubos; hierve en agua con sal 10 min hasta suavizar.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Sofr\u00ede cebolla y tomate picados en aceite 3 min; agrega chayote y ejotes.", "Sirve la pierna con el arroz y la mezcla de chayote y ejotes."]'::jsonb))),
    '{"es": ["Sazona 165g de pierna de cerdo con sal, ajo y or\u00e9gano; cocina en sart\u00e9n 6 min por lado.", "Cocina 130g de arroz blanco en 260ml de agua con sal, 18 min.", "Corta 100g de chayote en cubos; hierve en agua con sal 10 min hasta suavizar.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Sofr\u00ede cebolla y tomate picados en aceite 3 min; agrega chayote y ejotes.", "Sirve la pierna con el arroz y la mezcla de chayote y ejotes."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Rice, Chayote and Green Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d82ad37f-eb76-4cf9-81e8-858b477d21aa'::uuid, _rid, 'pierna de cerdo', 165, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4d2b1992-2549-46ff-851c-0fceba78a96a'::uuid, _rid, 'arroz blanco', 130, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c0b948c5-46cb-4dcd-8b4e-a6cc069040e7'::uuid, _rid, 'chayote', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fb1dffca-a52b-4915-88cf-ad60a33c3253'::uuid, _rid, 'ejotes', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c9dbc211-b90f-4a14-b615-616afeaf22af'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ed8ed297-4fbc-417e-be4a-aeced0fea458'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('eb40e9ae-3cf2-4ca4-b3ab-30453d5e0ceb'::uuid, _rid, 'tomate', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '34fba222-e737-4cd4-a0c1-3453b0ff4082'::uuid,
    'Grilled Pork Loin with Potato and Carrot', '{"es": "Lomo de cerdo a la plancha con papa y zanahoria"}'::jsonb,
    'Lomo de cerdo a la plancha con papa cocida, zanahoria y arroz.', '{"es": "Lomo de cerdo a la plancha con papa cocida, zanahoria y arroz."}'::jsonb,
    610, 50, 57, 20, 4, 4, 430, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 165g de lomo de cerdo con sal, pimienta y ajo en polvo.", "Cocina en plancha o sart\u00e9n caliente con aceite, 5-6 min por lado.", "Hierve 150g de papa en cubos en agua con sal, 15 min; escurre.", "Cocina 80g de zanahoria en rodajas en la misma agua, 10 min.", "Cocina 60g de arroz blanco en 120ml de agua con sal, 18 min.", "Sirve el lomo rebanado con la papa, zanahoria y arroz."]'::jsonb))),
    '{"es": ["Sazona 165g de lomo de cerdo con sal, pimienta y ajo en polvo.", "Cocina en plancha o sart\u00e9n caliente con aceite, 5-6 min por lado.", "Hierve 150g de papa en cubos en agua con sal, 15 min; escurre.", "Cocina 80g de zanahoria en rodajas en la misma agua, 10 min.", "Cocina 60g de arroz blanco en 120ml de agua con sal, 18 min.", "Sirve el lomo rebanado con la papa, zanahoria y arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Grilled Pork Loin with Potato and Carrot';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('601adf64-e53a-483f-bd3b-bb90caf139eb'::uuid, _rid, 'lomo de cerdo', 165, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('76f148fa-ec53-4355-b738-1634e989e6cf'::uuid, _rid, 'papa', 150, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e68f2aa2-316c-4089-90a9-aaee2e392867'::uuid, _rid, 'zanahoria', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ea8f4f33-808b-4e8d-8079-1dc4730c387b'::uuid, _rid, 'arroz blanco', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9ba6c1f8-7f83-4604-9d83-dd9d412034b2'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('21d3a290-e458-4edb-93d9-f6f83ffbac37'::uuid, _rid, 'ajo', 5, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a4a1c7d9-ac5f-4ddf-be96-c84dd2edaadf'::uuid, _rid, 'cebolla blanca', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '85b18d24-f6e6-4d5e-af55-a77d901d4e42'::uuid,
    'Pork Chop with Yuca and Black Beans', '{"es": "Chuleta de cerdo con yuca y frijoles negros"}'::jsonb,
    'Almuerzo sustancioso con chuleta de cerdo, yuca cocida y frijoles negros.', '{"es": "Almuerzo sustancioso con chuleta de cerdo, yuca cocida y frijoles negros."}'::jsonb,
    638, 49, 65, 21, 9, 4, 440, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 150g de chuleta de cerdo con sal, comino y ajo; cocina en sart\u00e9n 6 min por lado.", "Pela 100g de yuca; hierve en agua con sal 20-25 min hasta suavizar; escurre.", "Calienta 90g de frijoles negros con sofrito de cebolla, tomate y ajo, 5 min.", "Saltea 60g de pimiento en tiras con aceite y cebolla 3 min.", "Trocea la yuca cocida en porciones; sazona con sal y jugo de lim\u00f3n.", "Sirve la chuleta con la yuca, los frijoles y los pimientos."]'::jsonb))),
    '{"es": ["Sazona 150g de chuleta de cerdo con sal, comino y ajo; cocina en sart\u00e9n 6 min por lado.", "Pela 100g de yuca; hierve en agua con sal 20-25 min hasta suavizar; escurre.", "Calienta 90g de frijoles negros con sofrito de cebolla, tomate y ajo, 5 min.", "Saltea 60g de pimiento en tiras con aceite y cebolla 3 min.", "Trocea la yuca cocida en porciones; sazona con sal y jugo de lim\u00f3n.", "Sirve la chuleta con la yuca, los frijoles y los pimientos."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Yuca and Black Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('38030250-c543-4d27-956a-61fc69e7722e'::uuid, _rid, 'chuleta de cerdo', 150, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a886ebae-49fd-4903-811d-55dce067f074'::uuid, _rid, 'yuca', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5ef6d98f-484d-4148-b33a-0ca2ea528baa'::uuid, _rid, 'frijoles negros cocidos', 90, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c6d3351d-c847-40da-a5ea-b6b445e9b98f'::uuid, _rid, 'aceite de oliva', 5, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d3df7649-9a2f-4e31-9aff-f7e3ead3b22a'::uuid, _rid, 'pimiento morrón', 40, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a8b59a60-9ca0-46f5-8ada-8fdeff423c07'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '30d33042-8440-436f-b5d6-5884c6e2eaaa'::uuid,
    'Stewed Pork Loin with Lentils and Potato', '{"es": "Lomo de cerdo guisado con lentejas y papa"}'::jsonb,
    'Guiso de lomo de cerdo con lentejas y papa, plato de cuchara completo.', '{"es": "Guiso de lomo de cerdo con lentejas y papa, plato de cuchara completo."}'::jsonb,
    580, 54, 49, 19, 9, 4, 450, 5,
    'lunch'::meal_time_enum, 35,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Corta 155g de lomo de cerdo en cubos de 3cm; sofr\u00ede con aceite y ajo dorado 3 min.", "Agrega cebolla picada, tomate triturado y especias; sofr\u00ede 4 min m\u00e1s.", "Incorpora 100g de lentejas y 600ml de agua; cocina a fuego medio 15 min.", "Agrega 120g de papa en cubos al guiso; cocina 15 min hasta que papa y lentejas est\u00e9n tiernas.", "Ajusta sal y pimienta; espolvorea cilantro fresco picado.", "Sirve el guiso caliente en plato hondo."]'::jsonb))),
    '{"es": ["Corta 155g de lomo de cerdo en cubos de 3cm; sofr\u00ede con aceite y ajo dorado 3 min.", "Agrega cebolla picada, tomate triturado y especias; sofr\u00ede 4 min m\u00e1s.", "Incorpora 100g de lentejas y 600ml de agua; cocina a fuego medio 15 min.", "Agrega 120g de papa en cubos al guiso; cocina 15 min hasta que papa y lentejas est\u00e9n tiernas.", "Ajusta sal y pimienta; espolvorea cilantro fresco picado.", "Sirve el guiso caliente en plato hondo."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Stewed Pork Loin with Lentils and Potato';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bd7b01e3-c573-456f-8af8-f1deff717ee3'::uuid, _rid, 'lomo de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8a6a9924-f7a0-41d1-a0f0-8ecd12b83777'::uuid, _rid, 'lentejas', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d87a88ec-f541-4149-9531-598dbd84aaee'::uuid, _rid, 'papa', 120, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d67c3fac-acbc-4706-a68b-d153ce1ea26d'::uuid, _rid, 'aceite de oliva', 5, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4bca8c0c-81d8-4f73-850f-f89e0f81da04'::uuid, _rid, 'tomate triturado', 70, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fa11fed4-09f1-477b-8139-1ad3f21f9dce'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8dba7839-c13d-4e42-827b-ddc8d5586628'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'ded2cdae-b0cc-4299-919a-ba268e7cd7c3'::uuid,
    'Pork Leg with Quinoa, Broccoli and Bell Pepper', '{"es": "Pierna de cerdo con quinoa, br\u00f3coli y pimientos"}'::jsonb,
    'Almuerzo completo con pierna de cerdo, quinoa, brócoli y pimientos coloridos.', '{"es": "Almuerzo completo con pierna de cerdo, quinoa, br\u00f3coli y pimientos coloridos."}'::jsonb,
    627, 57, 52, 20, 6, 4, 430, 5,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 165g de pierna de cerdo con sal, ajo, or\u00e9gano y aceite; hornea 200\u00b0C por 25 min.", "Cocina 170g de quinoa en 340ml de agua con sal, 15 min; esponja con tenedor.", "Blanquea 100g de br\u00f3coli en agua hirviendo 4 min; escurre.", "Saltea 80g de pimiento morr\u00f3n en tiras con aceite y ajo, 5 min hasta suavizar.", "Rebana la pierna de cerdo en medallones.", "Sirve sobre la quinoa con el br\u00f3coli y los pimientos salteados."]'::jsonb))),
    '{"es": ["Sazona 165g de pierna de cerdo con sal, ajo, or\u00e9gano y aceite; hornea 200\u00b0C por 25 min.", "Cocina 170g de quinoa en 340ml de agua con sal, 15 min; esponja con tenedor.", "Blanquea 100g de br\u00f3coli en agua hirviendo 4 min; escurre.", "Saltea 80g de pimiento morr\u00f3n en tiras con aceite y ajo, 5 min hasta suavizar.", "Rebana la pierna de cerdo en medallones.", "Sirve sobre la quinoa con el br\u00f3coli y los pimientos salteados."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Quinoa, Broccoli and Bell Pepper';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d347614f-8f10-493c-84c7-f832b3ccb991'::uuid, _rid, 'pierna de cerdo', 165, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d7d5bbe4-d025-4cf7-aabc-162c5c927486'::uuid, _rid, 'quinoa', 170, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f600cfa3-11ca-4f75-bd2f-675d099487e9'::uuid, _rid, 'brócoli', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('89307ad1-d05b-4382-b0e0-609a0b563c82'::uuid, _rid, 'pimiento morrón', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('52bae638-3c8f-4609-b625-f76117321cbd'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d74360f7-715a-40bc-a9b6-3c91e0ea03f1'::uuid, _rid, 'ajo', 5, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d7fb1fe0-071c-4c26-bdbc-4b21e9db21a2'::uuid, _rid, 'tomate', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'aa0bfcd1-4b93-4124-9f74-fce2bd4bdfae'::uuid,
    'Pork Loin with Corn, Beans and Corn Tortilla', '{"es": "Lomo de cerdo con ma\u00edz, frijoles y tortilla de ma\u00edz"}'::jsonb,
    'Almuerzo mexicano con lomo de cerdo, maíz tierno, frijoles y tortillas.', '{"es": "Almuerzo mexicano con lomo de cerdo, ma\u00edz tierno, frijoles y tortillas."}'::jsonb,
    638, 54, 66, 21, 9, 5, 440, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 150g de lomo de cerdo con sal, comino y chile; cocina en sart\u00e9n 6 min por lado.", "Calienta 70g de frijoles negros con 80g de ma\u00edz tierno cocido, ajo y comino, 5 min.", "Calienta 2 tortillas de ma\u00edz (60g total) en comal seco 1 min por lado.", "Sofr\u00ede 70g de tomate y cebolla en el aceite restante 3 min.", "Deshebra el lomo de cerdo cocido y mezcla con el sofrito.", "Sirve el cerdo sobre tortillas con la mezcla de ma\u00edz y frijoles."]'::jsonb))),
    '{"es": ["Sazona 150g de lomo de cerdo con sal, comino y chile; cocina en sart\u00e9n 6 min por lado.", "Calienta 70g de frijoles negros con 80g de ma\u00edz tierno cocido, ajo y comino, 5 min.", "Calienta 2 tortillas de ma\u00edz (60g total) en comal seco 1 min por lado.", "Sofr\u00ede 70g de tomate y cebolla en el aceite restante 3 min.", "Deshebra el lomo de cerdo cocido y mezcla con el sofrito.", "Sirve el cerdo sobre tortillas con la mezcla de ma\u00edz y frijoles."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Corn, Beans and Corn Tortilla';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e7ebc377-ac88-4b38-99de-0c354ba0f8d9'::uuid, _rid, 'lomo de cerdo', 150, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1923b9ef-d334-4166-81c4-ebb717b78b38'::uuid, _rid, 'maíz tierno', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e34bde86-f1b1-4d2d-8af5-c5fa08306ed1'::uuid, _rid, 'frijoles negros cocidos', 70, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('39fbd8a5-5d98-4488-9839-b5384f612d4f'::uuid, _rid, 'tortilla de maíz', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7b0d12e3-132f-4f6a-8368-8ef92a8315c0'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6bba7b33-ed83-4dea-b113-6a8774c2732a'::uuid, _rid, 'tomate', 40, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('280044e7-f48f-4cd6-96df-60ced9ad6314'::uuid, _rid, 'cebolla blanca', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'b5bbb406-c14f-4a33-b889-a68a928f4d0a'::uuid,
    'Pork Chop with Sweet Potato, Spinach and Beans', '{"es": "Chuleta de cerdo con camote, espinacas y frijoles"}'::jsonb,
    'Almuerzo nutritivo con chuleta de cerdo, camote, espinacas y frijoles.', '{"es": "Almuerzo nutritivo con chuleta de cerdo, camote, espinacas y frijoles."}'::jsonb,
    592, 52, 52, 20, 9, 5, 430, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 155g de chuleta de cerdo con sal y ajo; cocina en sart\u00e9n con aceite 6 min por lado.", "Hierve 150g de camote en cubos en agua con sal, 15 min; escurre.", "Saltea 80g de espinacas con ajo picado en aceite, 2 min hasta marchitar.", "Calienta 60g de frijoles negros con tomate y cebolla picados, 4 min.", "Acomoda el camote cocido, apl\u00e1stalo ligeramente con tenedor y sazona.", "Sirve la chuleta con el camote, las espinacas salteadas y los frijoles."]'::jsonb))),
    '{"es": ["Sazona 155g de chuleta de cerdo con sal y ajo; cocina en sart\u00e9n con aceite 6 min por lado.", "Hierve 150g de camote en cubos en agua con sal, 15 min; escurre.", "Saltea 80g de espinacas con ajo picado en aceite, 2 min hasta marchitar.", "Calienta 60g de frijoles negros con tomate y cebolla picados, 4 min.", "Acomoda el camote cocido, apl\u00e1stalo ligeramente con tenedor y sazona.", "Sirve la chuleta con el camote, las espinacas salteadas y los frijoles."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Sweet Potato, Spinach and Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('40c130a0-e0ce-4e84-a3f3-359406ac1e6d'::uuid, _rid, 'chuleta de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d81df905-4f70-42ba-a55a-8ccdacd23309'::uuid, _rid, 'camote', 150, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7d7d1bdf-f3cd-4937-9488-d2a96e733561'::uuid, _rid, 'espinacas', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5a54bd8c-8369-4c7e-b39d-7285074ed422'::uuid, _rid, 'frijoles negros cocidos', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1684a9fb-7044-4af0-bb13-12c83dd0e050'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9bc76072-514b-4e91-955d-9e834051b29b'::uuid, _rid, 'ajo', 5, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('cc21d3c4-6641-4080-a11b-34ae2ca9840b'::uuid, _rid, 'tomate', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'f5dc8945-d0eb-45bc-8e43-99ef354434e5'::uuid,
    'Roasted Pork Loin with Rice and Green Beans', '{"es": "Lomo de cerdo al horno con arroz y ejotes"}'::jsonb,
    'Lomo de cerdo al horno con arroz blanco y ejotes tiernos.', '{"es": "Lomo de cerdo al horno con arroz blanco y ejotes tiernos."}'::jsonb,
    605, 51, 54, 20, 5, 3, 420, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Precalienta horno a 200\u00b0C. Sazona 165g de lomo de cerdo con sal, ajo y p\u00e1prika.", "Hornea 25 min hasta temperatura interna de 70\u00b0C; reposa 5 min y rebana.", "Cocina 140g de arroz blanco en 280ml de agua con sal, 18 min a fuego bajo.", "Blanquea 100g de ejotes en agua hirviendo con sal, 4 min; escurre.", "Saltea los ejotes en sart\u00e9n con aceite, pimiento y cebolla picados, 3 min.", "Sirve el lomo con el arroz y los ejotes salteados con pimiento."]'::jsonb))),
    '{"es": ["Precalienta horno a 200\u00b0C. Sazona 165g de lomo de cerdo con sal, ajo y p\u00e1prika.", "Hornea 25 min hasta temperatura interna de 70\u00b0C; reposa 5 min y rebana.", "Cocina 140g de arroz blanco en 280ml de agua con sal, 18 min a fuego bajo.", "Blanquea 100g de ejotes en agua hirviendo con sal, 4 min; escurre.", "Saltea los ejotes en sart\u00e9n con aceite, pimiento y cebolla picados, 3 min.", "Sirve el lomo con el arroz y los ejotes salteados con pimiento."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Roasted Pork Loin with Rice and Green Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0b49b40b-cbdb-4e14-b630-e8482f2692ad'::uuid, _rid, 'lomo de cerdo', 165, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8fc13083-cd96-4dc9-ba05-6e5742a60cf1'::uuid, _rid, 'arroz blanco', 140, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('78ee509c-8244-4122-ab66-1712f324c48c'::uuid, _rid, 'ejotes', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0b7b90e8-7ea3-4687-a355-5bac867cea30'::uuid, _rid, 'aceite de oliva', 5, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f136c975-5a0d-42c4-8556-ce2bb7bfcd97'::uuid, _rid, 'pimiento morrón', 40, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bff44b70-709b-4b17-9b20-856559e600d0'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'fe880994-cfb4-4943-9328-596f231f47cd'::uuid,
    'Pork Leg with Chickpeas, Bell Pepper and Rice', '{"es": "Pierna de cerdo con garbanzos, pimientos y arroz"}'::jsonb,
    'Almuerzo mediterráneo-latino con pierna de cerdo, garbanzos y pimientos.', '{"es": "Almuerzo mediterr\u00e1neo-latino con pierna de cerdo, garbanzos y pimientos."}'::jsonb,
    623, 55, 56, 19, 7, 4, 440, 5,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 155g de pierna de cerdo con sal, p\u00e1prika y ajo; cocina en sart\u00e9n 6 min por lado.", "Saltea 80g de pimiento morr\u00f3n en tiras con cebolla y ajo en aceite, 4 min.", "Agrega 90g de garbanzos cocidos al sofrito; sazona con comino y pizca de sal, 4 min.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min.", "Rebana la pierna de cerdo en l\u00e1minas.", "Sirve la pierna sobre el arroz con los garbanzos y pimientos encima."]'::jsonb))),
    '{"es": ["Sazona 155g de pierna de cerdo con sal, p\u00e1prika y ajo; cocina en sart\u00e9n 6 min por lado.", "Saltea 80g de pimiento morr\u00f3n en tiras con cebolla y ajo en aceite, 4 min.", "Agrega 90g de garbanzos cocidos al sofrito; sazona con comino y pizca de sal, 4 min.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min.", "Rebana la pierna de cerdo en l\u00e1minas.", "Sirve la pierna sobre el arroz con los garbanzos y pimientos encima."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Chickpeas, Bell Pepper and Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d8e377fb-8232-49e4-b28e-e7a3c52a3907'::uuid, _rid, 'pierna de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('92e2a0a4-9d32-4120-a612-f92386ff6f7f'::uuid, _rid, 'garbanzos cocidos', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d9f01be5-7a42-427e-9019-0fe709824b31'::uuid, _rid, 'pimiento morrón', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9cedcfe3-d0b0-4175-82b4-2b6f314062d4'::uuid, _rid, 'arroz blanco', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3581fc94-7a9b-43d3-81dd-8bc08ddb9b3d'::uuid, _rid, 'aceite de oliva', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('64e44c3b-f176-40de-8550-088c5840726d'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bdb4be13-1bfc-42bb-af4c-1736a68ab1b2'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'e1cc4439-5678-4bcd-9734-be326dc91b93'::uuid,
    'Pork Loin Marinated with Beans and Corn Tortillas', '{"es": "Lomo de cerdo en adobo con frijoles y tortillas de ma\u00edz"}'::jsonb,
    'Lomo de cerdo marinado en adobo rojo, acompañado de frijoles y tortillas.', '{"es": "Lomo de cerdo marinado en adobo rojo, acompa\u00f1ado de frijoles y tortillas."}'::jsonb,
    616, 55, 58, 20, 9, 4, 460, 6,
    'lunch'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Mezcla chile guajillo molido, ajo, vinagre, sal y comino para el adobo.", "Marina 155g de lomo de cerdo en el adobo por 15 min m\u00ednimo.", "Cocina el lomo marinado en sart\u00e9n con aceite a fuego medio, 6 min por lado.", "Calienta 100g de frijoles negros con cebolla y ajo picados, 5 min.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Rebana el lomo y sirve con los frijoles sobre las tortillas."]'::jsonb))),
    '{"es": ["Mezcla chile guajillo molido, ajo, vinagre, sal y comino para el adobo.", "Marina 155g de lomo de cerdo en el adobo por 15 min m\u00ednimo.", "Cocina el lomo marinado en sart\u00e9n con aceite a fuego medio, 6 min por lado.", "Calienta 100g de frijoles negros con cebolla y ajo picados, 5 min.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Rebana el lomo y sirve con los frijoles sobre las tortillas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin Marinated with Beans and Corn Tortillas';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3f0bcd53-3b18-47d6-a9ae-a6cfaebe983f'::uuid, _rid, 'lomo de cerdo', 155, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2624f183-f85f-41f8-acce-639daa79279f'::uuid, _rid, 'frijoles negros cocidos', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0e856997-cd85-4e54-9bdc-faff2b1e0c1c'::uuid, _rid, 'tortilla de maíz', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d1b532b6-69d8-4395-a7b1-314550c1ca83'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ec338c5c-02c1-4499-b1cb-484e4b9cc523'::uuid, _rid, 'chile guajillo', 10, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c5c9ef9d-6e78-49a1-bf6a-b75718c74615'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4beb699d-aed9-4d4a-ba33-2d425c68a61c'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'cd54f2d6-b5b2-4d7e-b6e4-6b8b83bc6ed8'::uuid,
    'Roasted Pork Loin with Brown Rice and Spinach', '{"es": "Lomo de cerdo al horno con arroz integral y espinacas"}'::jsonb,
    'Cena ligera con lomo de cerdo al horno, arroz integral y espinacas salteadas.', '{"es": "Cena ligera con lomo de cerdo al horno, arroz integral y espinacas salteadas."}'::jsonb,
    439, 44, 28, 18, 3, 2, 370, 5,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Precalienta horno a 200\u00b0C. Sazona 140g de lomo de cerdo con sal, romero y ajo.", "Hornea 20-25 min hasta temperatura interna de 70\u00b0C; reposa 5 min.", "Cocina 90g de arroz integral en 200ml de agua con sal, 30 min.", "Saltea 100g de espinacas con 1 diente de ajo y aceite, 2 min hasta marchitar.", "Rebana el lomo de cerdo en medallones.", "Sirve el lomo con el arroz integral y las espinacas salteadas; exprime lim\u00f3n."]'::jsonb))),
    '{"es": ["Precalienta horno a 200\u00b0C. Sazona 140g de lomo de cerdo con sal, romero y ajo.", "Hornea 20-25 min hasta temperatura interna de 70\u00b0C; reposa 5 min.", "Cocina 90g de arroz integral en 200ml de agua con sal, 30 min.", "Saltea 100g de espinacas con 1 diente de ajo y aceite, 2 min hasta marchitar.", "Rebana el lomo de cerdo en medallones.", "Sirve el lomo con el arroz integral y las espinacas salteadas; exprime lim\u00f3n."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Roasted Pork Loin with Brown Rice and Spinach';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('328365d7-dde8-47f2-879a-2886e6023ca3'::uuid, _rid, 'lomo de cerdo', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d6dc111b-87bd-487d-8840-ed3b72b78a5a'::uuid, _rid, 'arroz integral', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d8660ed9-b35d-40ab-a595-99a3e2e19f9a'::uuid, _rid, 'espinacas', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1976e5c6-43cc-4d68-a808-48034c84b15b'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a17b56fd-fd10-4cbe-9a80-85327e8ad3c0'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a6d3cb55-572e-4725-85c8-aebb061f8c11'::uuid, _rid, 'tomate', 30, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '2e4811f6-fdbf-463d-a08d-87d392921490'::uuid,
    'Pork Chop with Potato and Green Beans', '{"es": "Chuleta de cerdo a la plancha con papa y ejotes"}'::jsonb,
    'Cena sencilla con chuleta de cerdo a la plancha, papa cocida y ejotes.', '{"es": "Cena sencilla con chuleta de cerdo a la plancha, papa cocida y ejotes."}'::jsonb,
    453, 40, 36, 18, 4, 3, 380, 5,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 135g de chuleta de cerdo con sal, pimienta y ajo en polvo.", "Cocina en sart\u00e9n caliente con aceite a fuego medio, 5 min por lado.", "Hierve 130g de papa en cubos en agua con sal, 15 min; escurre.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea los ejotes con aceite y pizca de ajo picado, 2 min.", "Sirve la chuleta con la papa y los ejotes; sazona con lim\u00f3n."]'::jsonb))),
    '{"es": ["Sazona 135g de chuleta de cerdo con sal, pimienta y ajo en polvo.", "Cocina en sart\u00e9n caliente con aceite a fuego medio, 5 min por lado.", "Hierve 130g de papa en cubos en agua con sal, 15 min; escurre.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea los ejotes con aceite y pizca de ajo picado, 2 min.", "Sirve la chuleta con la papa y los ejotes; sazona con lim\u00f3n."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Potato and Green Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ac81459f-d077-454e-852a-54e2643df9e1'::uuid, _rid, 'chuleta de cerdo', 135, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('48d4a55a-0d0f-4edb-b4ca-dfe2e1a0c5a6'::uuid, _rid, 'papa', 130, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5e004068-f3bb-4d3f-b62c-6710e28a15db'::uuid, _rid, 'ejotes', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ffe93bf3-2dd2-43be-97f4-0297bd45cfcf'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('484e5ec3-e7fa-4994-9062-9c50a99f3802'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('97a83238-cfad-4686-92e5-cb78618b165b'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '417552d2-95b7-4ce1-92ef-c728741588ae'::uuid,
    'Pork Leg with Black Beans and Plantain', '{"es": "Pierna de cerdo con frijoles negros y pl\u00e1tano"}'::jsonb,
    'Cena con pierna de cerdo, frijoles negros y plátano maduro.', '{"es": "Cena con pierna de cerdo, frijoles negros y pl\u00e1tano maduro."}'::jsonb,
    489, 49, 43, 16, 8, 7, 380, 4,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de pierna de cerdo con sal, comino y ajo; cocina en sart\u00e9n 5 min por lado.", "Calienta 90g de frijoles negros con sofrito de cebolla, tomate y comino, 5 min.", "En sart\u00e9n con aceite m\u00ednimo, dora 80g de pl\u00e1tano maduro en rodajas 2 min por lado.", "Retira el pl\u00e1tano; en el mismo sart\u00e9n, sofr\u00ede 50g de cebolla y tomate 2 min.", "Rebana la pierna de cerdo en l\u00e1minas.", "Sirve la pierna con los frijoles, el pl\u00e1tano y el sofrito."]'::jsonb))),
    '{"es": ["Sazona 140g de pierna de cerdo con sal, comino y ajo; cocina en sart\u00e9n 5 min por lado.", "Calienta 90g de frijoles negros con sofrito de cebolla, tomate y comino, 5 min.", "En sart\u00e9n con aceite m\u00ednimo, dora 80g de pl\u00e1tano maduro en rodajas 2 min por lado.", "Retira el pl\u00e1tano; en el mismo sart\u00e9n, sofr\u00ede 50g de cebolla y tomate 2 min.", "Rebana la pierna de cerdo en l\u00e1minas.", "Sirve la pierna con los frijoles, el pl\u00e1tano y el sofrito."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Black Beans and Plantain';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('76e431fe-bc3e-48dd-96b1-ea97b4a3de19'::uuid, _rid, 'pierna de cerdo', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a5c47576-35ce-4c4e-98e6-ebe075d18c7e'::uuid, _rid, 'frijoles negros cocidos', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d64550f4-f7c5-40d6-a21c-5158e15f531f'::uuid, _rid, 'plátano maduro', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('89d41abd-c597-4667-8906-ff05aea57b37'::uuid, _rid, 'aceite de oliva', 3, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('81eece42-3404-4c9f-b06d-9cfbb4183cb2'::uuid, _rid, 'tomate', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bccd2c58-5c78-49ea-9ae3-6a563cecd050'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '6b45f67a-6f66-48f1-8adc-6b7738649d3a'::uuid,
    'Stewed Pork Loin with Lentils and Carrot', '{"es": "Lomo de cerdo guisado con lentejas y zanahoria"}'::jsonb,
    'Cena de guiso con lomo de cerdo, lentejas y zanahoria.', '{"es": "Cena de guiso con lomo de cerdo, lentejas y zanahoria."}'::jsonb,
    468, 49, 32, 17, 9, 3, 390, 5,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Corta 140g de lomo de cerdo en cubos de 3cm; dora en sart\u00e9n con aceite, 3 min.", "Agrega 110g de lentejas secas, 500ml de agua, cebolla, ajo y zanahoria en rodajas.", "Hierve, luego baja a fuego medio y cocina 20 min hasta que lentejas y zanahoria est\u00e9n tiernas.", "Agrega 70g de zanahoria en los \u00faltimos 10 min.", "Ajusta sal y pimienta; a\u00f1ade cilantro fresco picado.", "Sirve el guiso caliente con jugo de lim\u00f3n."]'::jsonb))),
    '{"es": ["Corta 140g de lomo de cerdo en cubos de 3cm; dora en sart\u00e9n con aceite, 3 min.", "Agrega 110g de lentejas secas, 500ml de agua, cebolla, ajo y zanahoria en rodajas.", "Hierve, luego baja a fuego medio y cocina 20 min hasta que lentejas y zanahoria est\u00e9n tiernas.", "Agrega 70g de zanahoria en los \u00faltimos 10 min.", "Ajusta sal y pimienta; a\u00f1ade cilantro fresco picado.", "Sirve el guiso caliente con jugo de lim\u00f3n."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Stewed Pork Loin with Lentils and Carrot';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ef25872e-ea88-4135-8c84-a59eb300ab18'::uuid, _rid, 'lomo de cerdo', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('839b0805-7caf-47e5-ba1a-f3e86e91d90f'::uuid, _rid, 'lentejas', 110, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9b42deb1-f87e-443d-b12e-8c6657cbd692'::uuid, _rid, 'zanahoria', 70, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e6128240-c72f-46af-89f2-946385de64b4'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('01151731-82b2-4b0b-82b8-93d3691e238b'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6cdf5a75-a511-4cf0-9377-b52f266915db'::uuid, _rid, 'ajo', 5, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a72205bb-e12b-457f-9a7f-2577c5e6ca3d'::uuid, _rid, 'tomate', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'bdb6d6f3-3bb1-4cad-a351-d6b6a4222bca'::uuid,
    'Pork Chop with Quinoa and Broccoli', '{"es": "Chuleta de cerdo a la plancha con quinoa y br\u00f3coli"}'::jsonb,
    'Cena con chuleta de cerdo a la plancha, quinoa y brócoli al vapor.', '{"es": "Cena con chuleta de cerdo a la plancha, quinoa y br\u00f3coli al vapor."}'::jsonb,
    481, 43, 34, 20, 5, 3, 380, 6,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 135g de chuleta de cerdo con sal, ajo y or\u00e9gano.", "Cocina en plancha o sart\u00e9n caliente con aceite, 5 min por lado.", "Cocina 110g de quinoa en 220ml de agua con sal, 15 min; esponja con tenedor.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min; escurre.", "Saltea el br\u00f3coli con ajo picado y aceite, 2 min.", "Sirve la chuleta sobre la quinoa con el br\u00f3coli al lado."]'::jsonb))),
    '{"es": ["Sazona 135g de chuleta de cerdo con sal, ajo y or\u00e9gano.", "Cocina en plancha o sart\u00e9n caliente con aceite, 5 min por lado.", "Cocina 110g de quinoa en 220ml de agua con sal, 15 min; esponja con tenedor.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min; escurre.", "Saltea el br\u00f3coli con ajo picado y aceite, 2 min.", "Sirve la chuleta sobre la quinoa con el br\u00f3coli al lado."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Quinoa and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4fc7fc93-a469-4a3d-98c9-7f30a2ddeec0'::uuid, _rid, 'chuleta de cerdo', 135, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('de795d12-61bf-484b-9a8e-0577c249578f'::uuid, _rid, 'quinoa', 110, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f6d207ec-1e65-499c-9a7c-872789f6f0cc'::uuid, _rid, 'brócoli', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7c42d3a7-937e-44cb-ad37-029555c170b6'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('de2be68c-f58c-44cd-a234-e3005a4d2079'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b8b5d48f-7211-4792-a8d1-53e4dafce709'::uuid, _rid, 'limón', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '73433f2d-2d7e-4023-ab2e-4bf085fdf3a9'::uuid,
    'Pork Leg in Tomato Sauce with Rice', '{"es": "Pierna de cerdo en salsa de tomate con arroz"}'::jsonb,
    'Pierna de cerdo guisada en salsa de tomate natural con arroz blanco.', '{"es": "Pierna de cerdo guisada en salsa de tomate natural con arroz blanco."}'::jsonb,
    477, 45, 38, 16, 2, 5, 400, 4,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 145g de pierna de cerdo en sart\u00e9n con aceite a fuego alto, 3 min por lado.", "Agrega 150g de tomate triturado, cebolla, ajo y or\u00e9gano; cocina 15 min a fuego medio.", "Cocina 100g de arroz blanco en 200ml de agua con sal, 18 min.", "Verifica que la pierna est\u00e9 tierna; ajusta sal y a\u00f1ade perejil picado.", "Rebana la pierna en medallones.", "Sirve el cerdo en salsa de tomate con el arroz."]'::jsonb))),
    '{"es": ["Dora 145g de pierna de cerdo en sart\u00e9n con aceite a fuego alto, 3 min por lado.", "Agrega 150g de tomate triturado, cebolla, ajo y or\u00e9gano; cocina 15 min a fuego medio.", "Cocina 100g de arroz blanco en 200ml de agua con sal, 18 min.", "Verifica que la pierna est\u00e9 tierna; ajusta sal y a\u00f1ade perejil picado.", "Rebana la pierna en medallones.", "Sirve el cerdo en salsa de tomate con el arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg in Tomato Sauce with Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('96a203f3-2264-4150-968f-70c2e0e43f01'::uuid, _rid, 'pierna de cerdo', 145, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3e9505bd-7797-4d0b-b10e-2bbb18d02cd1'::uuid, _rid, 'tomate triturado', 150, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3af5de2d-aaab-4075-a3ba-bb291681376d'::uuid, _rid, 'arroz blanco', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e8512e1f-f432-4903-a152-26096b891a06'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bff1aa8d-1cd6-4d35-84f8-4d577d772bd1'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('be802994-5c09-447b-a461-525664be177d'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '850a6c97-0f6a-4a68-8a29-cd62915ff04d'::uuid,
    'Pork Loin with Sweet Potato and Chayote', '{"es": "Lomo de cerdo con camote y chayote"}'::jsonb,
    'Cena con lomo de cerdo, camote y chayote al vapor.', '{"es": "Cena con lomo de cerdo, camote y chayote al vapor."}'::jsonb,
    449, 41, 35, 17, 5, 5, 360, 5,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de lomo de cerdo con sal, pimienta y comino; cocina en sart\u00e9n 5 min por lado.", "Hierve 120g de camote en cubos con 100g de chayote en trozos en agua con sal, 15 min.", "Escurre las verduras; saltea en sart\u00e9n con aceite, cebolla y ajo 3 min.", "Sazona las verduras con sal, pimienta y pizca de canela.", "Rebana el lomo de cerdo.", "Sirve el lomo con el camote y el chayote salteados."]'::jsonb))),
    '{"es": ["Sazona 140g de lomo de cerdo con sal, pimienta y comino; cocina en sart\u00e9n 5 min por lado.", "Hierve 120g de camote en cubos con 100g de chayote en trozos en agua con sal, 15 min.", "Escurre las verduras; saltea en sart\u00e9n con aceite, cebolla y ajo 3 min.", "Sazona las verduras con sal, pimienta y pizca de canela.", "Rebana el lomo de cerdo.", "Sirve el lomo con el camote y el chayote salteados."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Sweet Potato and Chayote';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e16a108d-02ae-4469-8f07-a73759f98c01'::uuid, _rid, 'lomo de cerdo', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8873badd-bea8-4f5f-aaf0-7a9c03959e39'::uuid, _rid, 'camote', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('81e5f47f-8ccd-491f-be04-8f69a5eafe40'::uuid, _rid, 'chayote', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f1db842f-4177-4ec7-899e-f6d47a5c32ed'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b679f17b-7da7-46f9-9d2d-ec6c148fac40'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f051fc4f-fe27-405f-a459-83ba23edc032'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '3f164e97-425f-47ae-928e-f52aa739ef83'::uuid,
    'Pork Chop with Chickpeas and Spinach', '{"es": "Chuleta de cerdo con garbanzos y espinacas"}'::jsonb,
    'Cena proteica con chuleta de cerdo, garbanzos y espinacas.', '{"es": "Cena proteica con chuleta de cerdo, garbanzos y espinacas."}'::jsonb,
    497, 47, 34, 20, 8, 3, 400, 6,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 135g de chuleta de cerdo con sal y p\u00e1prika; cocina en sart\u00e9n 5 min por lado.", "Sofr\u00ede cebolla y ajo en aceite hasta transparentes, 3 min.", "Agrega 100g de garbanzos cocidos al sofrito; sazona con comino y pizca de sal.", "A\u00f1ade 80g de espinacas; saltea 2 min hasta que marchiten.", "Mezcla bien los garbanzos y espinacas; ajusta sal.", "Sirve la chuleta con la mezcla de garbanzos y espinacas."]'::jsonb))),
    '{"es": ["Sazona 135g de chuleta de cerdo con sal y p\u00e1prika; cocina en sart\u00e9n 5 min por lado.", "Sofr\u00ede cebolla y ajo en aceite hasta transparentes, 3 min.", "Agrega 100g de garbanzos cocidos al sofrito; sazona con comino y pizca de sal.", "A\u00f1ade 80g de espinacas; saltea 2 min hasta que marchiten.", "Mezcla bien los garbanzos y espinacas; ajusta sal.", "Sirve la chuleta con la mezcla de garbanzos y espinacas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Chickpeas and Spinach';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('31847c92-0c05-492f-96be-5eadd9a1f2a9'::uuid, _rid, 'chuleta de cerdo', 135, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f08b9602-c65b-4f12-be37-992788bb0eda'::uuid, _rid, 'garbanzos cocidos', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d708925d-7163-4722-9977-f57f91ba57a5'::uuid, _rid, 'espinacas', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('787e86e0-212a-449d-aba4-4dd91567e914'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('469dcb1d-a737-4d85-b2dc-55e66fdec9d1'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('af88c869-cc22-4e84-9aa5-dad04155c255'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '2a540cf0-5ed0-407c-b8b3-d21ee8cd8b6e'::uuid,
    'Pork Leg with Yuca and Broccoli', '{"es": "Pierna de cerdo con yuca y br\u00f3coli"}'::jsonb,
    'Cena con pierna de cerdo, yuca cocida y brócoli al vapor.', '{"es": "Cena con pierna de cerdo, yuca cocida y br\u00f3coli al vapor."}'::jsonb,
    493, 44, 44, 16, 3, 3, 380, 4,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 145g de pierna de cerdo con sal, ajo y or\u00e9gano; cocina en sart\u00e9n 5 min por lado.", "Pela 90g de yuca; hierve en agua con sal 20 min hasta suavizar.", "Blanquea 80g de br\u00f3coli en agua hirviendo con sal, 4 min.", "Sofr\u00ede la yuca en trozos con aceite y cebolla picada, 3 min para dorar.", "Saltea el br\u00f3coli con ajo picado, 2 min.", "Sirve la pierna con la yuca dorada y el br\u00f3coli."]'::jsonb))),
    '{"es": ["Sazona 145g de pierna de cerdo con sal, ajo y or\u00e9gano; cocina en sart\u00e9n 5 min por lado.", "Pela 90g de yuca; hierve en agua con sal 20 min hasta suavizar.", "Blanquea 80g de br\u00f3coli en agua hirviendo con sal, 4 min.", "Sofr\u00ede la yuca en trozos con aceite y cebolla picada, 3 min para dorar.", "Saltea el br\u00f3coli con ajo picado, 2 min.", "Sirve la pierna con la yuca dorada y el br\u00f3coli."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Yuca and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1dfcff8d-b5e1-43a0-8448-919d06ce413e'::uuid, _rid, 'pierna de cerdo', 145, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0970b3a5-bbe0-4456-844a-60076e4bcc18'::uuid, _rid, 'yuca', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('33e610c6-6354-42c2-aab9-28621618e2fc'::uuid, _rid, 'brócoli', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bd44c1a9-bbe7-4510-a0f5-a409dce9ec97'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f12437eb-49fe-455a-8195-95328ee5eb7e'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b045d188-6d48-4bef-9169-cd8e00f27af8'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '2e58e861-28e8-46f8-8694-43fb8a29c96c'::uuid,
    'Pork Loin with Corn and Green Beans', '{"es": "Lomo de cerdo con ma\u00edz y ejotes"}'::jsonb,
    'Cena con lomo de cerdo a la plancha, maíz tierno y ejotes.', '{"es": "Cena con lomo de cerdo a la plancha, ma\u00edz tierno y ejotes."}'::jsonb,
    478, 46, 37, 19, 4, 4, 380, 5,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 145g de lomo de cerdo con sal, pimienta y comino; cocina en plancha 5 min por lado.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea 130g de ma\u00edz tierno cocido con los ejotes, aceite y cebolla, 4 min.", "Agrega 60g de tomate picado y sofr\u00ede 2 min m\u00e1s.", "Rebana el lomo de cerdo en medallones.", "Sirve el lomo con la mezcla de ma\u00edz y ejotes."]'::jsonb))),
    '{"es": ["Sazona 145g de lomo de cerdo con sal, pimienta y comino; cocina en plancha 5 min por lado.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea 130g de ma\u00edz tierno cocido con los ejotes, aceite y cebolla, 4 min.", "Agrega 60g de tomate picado y sofr\u00ede 2 min m\u00e1s.", "Rebana el lomo de cerdo en medallones.", "Sirve el lomo con la mezcla de ma\u00edz y ejotes."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Loin with Corn and Green Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a5a5bb6a-7239-42c6-a5bf-6049fe1d79e4'::uuid, _rid, 'lomo de cerdo', 145, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e0c3abd5-0a82-468c-95cd-9a1fd1775cdc'::uuid, _rid, 'maíz tierno', 130, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b37a912b-9fef-456e-805d-a0130c5e5abd'::uuid, _rid, 'ejotes', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8c0f934a-8982-4454-9f10-334f15716501'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('cd5d0449-c6ed-43f2-a14a-f7b7e4c1d687'::uuid, _rid, 'tomate', 60, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('552e586f-9f64-4a48-8b57-4b9b09c2910c'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '7890e1e6-182a-4de4-b292-64fb35d5f538'::uuid,
    'Pork Chop with Rice and Black Beans', '{"es": "Chuleta de cerdo con arroz y frijoles negros"}'::jsonb,
    'Cena sencilla con chuleta de cerdo, arroz blanco y frijoles.', '{"es": "Cena sencilla con chuleta de cerdo, arroz blanco y frijoles."}'::jsonb,
    499, 41, 44, 18, 5, 3, 390, 5,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 130g de chuleta de cerdo con sal, ajo y comino; cocina en sart\u00e9n 5 min por lado.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min.", "Calienta 50g de frijoles negros con sofrito de cebolla, tomate y ajo, 4 min.", "Saltea 80g de zanahoria en rodajas con aceite hasta suavizar, 5 min.", "Mezcla la zanahoria con los frijoles.", "Sirve la chuleta con el arroz y los frijoles con zanahoria."]'::jsonb))),
    '{"es": ["Sazona 130g de chuleta de cerdo con sal, ajo y comino; cocina en sart\u00e9n 5 min por lado.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min.", "Calienta 50g de frijoles negros con sofrito de cebolla, tomate y ajo, 4 min.", "Saltea 80g de zanahoria en rodajas con aceite hasta suavizar, 5 min.", "Mezcla la zanahoria con los frijoles.", "Sirve la chuleta con el arroz y los frijoles con zanahoria."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Chop with Rice and Black Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d2b4c11d-3932-460d-88ca-865c72e9f47a'::uuid, _rid, 'chuleta de cerdo', 130, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c0859163-ecc5-41c2-a156-7aa57e79281a'::uuid, _rid, 'arroz blanco', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5754e917-9e39-4073-bd41-4ae32310a9fa'::uuid, _rid, 'frijoles negros cocidos', 50, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d16212e0-7b16-4804-aa1e-eb8a764ff038'::uuid, _rid, 'zanahoria', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('02b0ea86-f60d-4424-9406-833257061c33'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('88fc6b49-2077-4ab1-89d1-13225e9dc52e'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'bfcfecc3-57e8-4def-9091-213c0e6a9859'::uuid,
    'Pork Leg with Cactus and Black Beans', '{"es": "Pierna de cerdo con nopales y frijoles negros"}'::jsonb,
    'Cena mexicana con pierna de cerdo, nopales y frijoles negros.', '{"es": "Cena mexicana con pierna de cerdo, nopales y frijoles negros."}'::jsonb,
    451, 49, 30, 15, 10, 3, 380, 4,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de pierna de cerdo con sal, ajo y comino; cocina en sart\u00e9n 5 min por lado.", "Lava y trocea 100g de nopales; cocina en sart\u00e9n seca con sal 5 min.", "Calienta 90g de frijoles negros con cebolla y ajo picados, 4 min.", "Mezcla los nopales con los frijoles; sazona con comino y sal.", "Rebana la pierna de cerdo.", "Sirve la pierna con los nopales y frijoles."]'::jsonb))),
    '{"es": ["Sazona 140g de pierna de cerdo con sal, ajo y comino; cocina en sart\u00e9n 5 min por lado.", "Lava y trocea 100g de nopales; cocina en sart\u00e9n seca con sal 5 min.", "Calienta 90g de frijoles negros con cebolla y ajo picados, 4 min.", "Mezcla los nopales con los frijoles; sazona con comino y sal.", "Rebana la pierna de cerdo.", "Sirve la pierna con los nopales y frijoles."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['pork']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Pork Leg with Cactus and Black Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f1e6f526-4d45-4a3f-b1fb-b5f5b29cdb02'::uuid, _rid, 'pierna de cerdo', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c16de798-5bc1-4ebc-a583-1cf09add31a7'::uuid, _rid, 'nopales', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('38e0f08b-33ac-49ac-b92a-9074f237db9c'::uuid, _rid, 'frijoles negros cocidos', 90, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('78e8a46d-81c2-4c94-b6d7-83e07e7eaf8e'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3f23e0f6-f67a-4614-9a30-946e95cab479'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b0a8c2a1-0503-4f90-a104-89105991934f'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '9eedb865-e772-49b0-8dad-fb5d4d283530'::uuid,
    'Beef Steak with Rice and Broccoli', '{"es": "Bistec de res con arroz y br\u00f3coli"}'::jsonb,
    'Cena con bistec de res a la plancha, arroz blanco y brócoli al vapor.', '{"es": "Cena con bistec de res a la plancha, arroz blanco y br\u00f3coli al vapor."}'::jsonb,
    514, 45, 36, 20, 3, 3, 430, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 150g de bistec de res con sal, pimienta y ajo.", "Cocina en plancha o sart\u00e9n caliente con aceite, 4 min por lado para t\u00e9rmino medio.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min; escurre.", "Saltea el br\u00f3coli con ajo picado y aceite, 2 min.", "Rebana el bistec; sirve con el arroz y el br\u00f3coli."]'::jsonb))),
    '{"es": ["Sazona 150g de bistec de res con sal, pimienta y ajo.", "Cocina en plancha o sart\u00e9n caliente con aceite, 4 min por lado para t\u00e9rmino medio.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min; escurre.", "Saltea el br\u00f3coli con ajo picado y aceite, 2 min.", "Rebana el bistec; sirve con el arroz y el br\u00f3coli."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak with Rice and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('99cdd7be-1b30-452c-bf69-732070e77e14'::uuid, _rid, 'bistec de res', 150, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('efff49be-42f7-4e05-88b1-bb564de891e0'::uuid, _rid, 'arroz blanco', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c427986b-ba3b-4761-8cbf-5383506cc82b'::uuid, _rid, 'brócoli', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('53af5c0b-ddeb-4d4c-a559-db64218dc677'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4d42ab19-e576-43d2-b0cf-da80d16e3750'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('51a1eaac-f0a5-4a16-ab4c-ac5f2d09340a'::uuid, _rid, 'cebolla blanca', 30, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '5a1d07b7-f8ca-4d62-a255-e973425ab24f'::uuid,
    'Beef Tenderloin with Potato and Green Beans', '{"es": "Lomo de res con papa y ejotes"}'::jsonb,
    'Cena con lomo de res a la plancha, papa cocida y ejotes.', '{"es": "Cena con lomo de res a la plancha, papa cocida y ejotes."}'::jsonb,
    485, 42, 36, 21, 4, 3, 410, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de lomo de res con sal, pimienta y romero.", "Cocina en sart\u00e9n caliente con aceite, 4-5 min por lado.", "Hierve 130g de papa en cubos en agua con sal, 15 min; escurre.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea los ejotes con aceite, ajo y pizca de sal, 2 min.", "Rebana el lomo; sirve con la papa y los ejotes."]'::jsonb))),
    '{"es": ["Sazona 140g de lomo de res con sal, pimienta y romero.", "Cocina en sart\u00e9n caliente con aceite, 4-5 min por lado.", "Hierve 130g de papa en cubos en agua con sal, 15 min; escurre.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea los ejotes con aceite, ajo y pizca de sal, 2 min.", "Rebana el lomo; sirve con la papa y los ejotes."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Tenderloin with Potato and Green Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1e1434b7-a48a-4f19-b8ce-34cadeac3f6f'::uuid, _rid, 'lomo de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('56b22e08-df4e-4128-b397-d51a9c023cdf'::uuid, _rid, 'papa', 130, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c9c24c13-2870-4efd-95fb-a4f9793d8530'::uuid, _rid, 'ejotes', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('da474c54-8a77-42f2-9b60-68928358e0f6'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ba2226b2-3314-42fd-bacf-d7820ccaeb81'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8551eabc-9be8-4527-81a8-8965deed024a'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '7b871ee8-3590-41a6-b34d-1e6b5826e943'::uuid,
    'Ground Beef with Black Beans and Brown Rice', '{"es": "Carne molida de res con frijoles negros y arroz integral"}'::jsonb,
    'Cena con carne molida de res, frijoles negros y arroz integral.', '{"es": "Cena con carne molida de res, frijoles negros y arroz integral."}'::jsonb,
    548, 45, 45, 21, 9, 3, 450, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Cocina 130g de carne molida de res en sart\u00e9n con aceite a fuego medio, rompi\u00e9ndola 8 min.", "Agrega cebolla, ajo y tomate picados; sofr\u00ede 4 min m\u00e1s.", "Incorpora 90g de frijoles negros cocidos; sazona con comino y sal; calienta 3 min.", "Cocina 80g de arroz integral en 180ml de agua con sal, 30 min.", "Ajusta la saz\u00f3n de la carne molida con frijoles.", "Sirve la carne molida con frijoles sobre el arroz integral."]'::jsonb))),
    '{"es": ["Cocina 130g de carne molida de res en sart\u00e9n con aceite a fuego medio, rompi\u00e9ndola 8 min.", "Agrega cebolla, ajo y tomate picados; sofr\u00ede 4 min m\u00e1s.", "Incorpora 90g de frijoles negros cocidos; sazona con comino y sal; calienta 3 min.", "Cocina 80g de arroz integral en 180ml de agua con sal, 30 min.", "Ajusta la saz\u00f3n de la carne molida con frijoles.", "Sirve la carne molida con frijoles sobre el arroz integral."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Ground Beef with Black Beans and Brown Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fcc6379f-28fb-4622-9fdc-953064f0b4f6'::uuid, _rid, 'carne molida de res (90% magra)', 130, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5a5145d1-88de-4a44-a738-59f55688b1d8'::uuid, _rid, 'frijoles negros cocidos', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('35fbe037-e0a2-4bfd-8536-c1fe80c12c28'::uuid, _rid, 'arroz integral', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9fd360ed-08d5-4af8-b169-08fcbb9050d2'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('12e8f795-e53d-44ce-91bf-ba31a1056704'::uuid, _rid, 'tomate', 50, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5f8c37ba-acfa-4b80-8529-5196b20880bf'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '27d55462-afed-4414-b489-f9d5c406df18'::uuid,
    'Beef Steak with Quinoa and Spinach', '{"es": "Bistec de res con quinoa y espinacas"}'::jsonb,
    'Cena con bistec de res, quinoa y espinacas salteadas.', '{"es": "Cena con bistec de res, quinoa y espinacas salteadas."}'::jsonb,
    496, 46, 31, 21, 5, 2, 420, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de bistec de res con sal, pimienta y ajo en polvo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Cocina 110g de quinoa en 220ml de agua con sal, 15 min; esponja con tenedor.", "Saltea 100g de espinacas con ajo picado y aceite, 2 min.", "Rebana el bistec en tiras finas.", "Sirve las tiras de bistec sobre la quinoa con las espinacas."]'::jsonb))),
    '{"es": ["Sazona 140g de bistec de res con sal, pimienta y ajo en polvo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Cocina 110g de quinoa en 220ml de agua con sal, 15 min; esponja con tenedor.", "Saltea 100g de espinacas con ajo picado y aceite, 2 min.", "Rebana el bistec en tiras finas.", "Sirve las tiras de bistec sobre la quinoa con las espinacas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak with Quinoa and Spinach';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('59adab32-1bdf-4186-b051-842d50c9f4a3'::uuid, _rid, 'bistec de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e995a6b1-66b9-4821-ac50-7c8bc31a612b'::uuid, _rid, 'quinoa', 110, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('82073c28-6e3b-46a2-8099-d90a260ae4dc'::uuid, _rid, 'espinacas', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2595d5b9-b967-4905-bf57-2b989f16ef6e'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ef4a3359-2ae6-4cd0-9dcc-379d1ba98cd8'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('99694abd-6a7e-4ab0-a277-950d8f3bb912'::uuid, _rid, 'limón', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '91b6841b-109f-41ec-983e-767bf955a119'::uuid,
    'Beef Tenderloin with Lentils and Carrot', '{"es": "Lomo de res con lentejas y zanahoria"}'::jsonb,
    'Cena con lomo de res, lentejas cocidas y zanahoria.', '{"es": "Cena con lomo de res, lentejas cocidas y zanahoria."}'::jsonb,
    503, 49, 32, 21, 9, 3, 420, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de lomo de res con sal, pimienta y romero; cocina en sart\u00e9n 4 min por lado.", "Cocina 110g de lentejas en agua con sal, ajo y laurel, 20 min.", "Sofr\u00ede 80g de zanahoria en rodajas con cebolla y aceite, 5 min.", "Mezcla las lentejas con la zanahoria salteada; sazona con comino.", "Rebana el lomo de res.", "Sirve el lomo con las lentejas y zanahoria."]'::jsonb))),
    '{"es": ["Sazona 140g de lomo de res con sal, pimienta y romero; cocina en sart\u00e9n 4 min por lado.", "Cocina 110g de lentejas en agua con sal, ajo y laurel, 20 min.", "Sofr\u00ede 80g de zanahoria en rodajas con cebolla y aceite, 5 min.", "Mezcla las lentejas con la zanahoria salteada; sazona con comino.", "Rebana el lomo de res.", "Sirve el lomo con las lentejas y zanahoria."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Tenderloin with Lentils and Carrot';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('931639ce-42af-41ce-b5ac-ece4bffa04ee'::uuid, _rid, 'lomo de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('92be2d2a-99a9-4110-afcf-a63bd8786bd4'::uuid, _rid, 'lentejas cocidas', 110, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('68f12e20-2296-47b4-b0d7-562b7e8154f9'::uuid, _rid, 'zanahoria', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e4385d38-1a51-4f05-830c-0068a62c97c8'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3fadb625-9317-44a2-8c8e-1d3a7abb7bc7'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('75f46e4a-cd90-4d68-aa30-06c415f20bea'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'b424c4a6-fef5-4d2f-bb34-f88357f097a3'::uuid,
    'Ground Beef with Potato, Chayote and Beans', '{"es": "Carne molida de res con papa, chayote y frijoles"}'::jsonb,
    'Guiso de carne molida con papa, chayote y frijoles.', '{"es": "Guiso de carne molida con papa, chayote y frijoles."}'::jsonb,
    544, 43, 48, 20, 7, 4, 450, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 130g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega cebolla, ajo, tomate y especias; sofr\u00ede 4 min.", "Incorpora 120g de papa y 100g de chayote en cubos; a\u00f1ade 300ml de agua.", "Hierve y baja a fuego medio 15 min hasta que papa y chayote est\u00e9n tiernos.", "Agrega 60g de frijoles cocidos; calienta 3 min y ajusta sal.", "Sirve el guiso caliente."]'::jsonb))),
    '{"es": ["Dora 130g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega cebolla, ajo, tomate y especias; sofr\u00ede 4 min.", "Incorpora 120g de papa y 100g de chayote en cubos; a\u00f1ade 300ml de agua.", "Hierve y baja a fuego medio 15 min hasta que papa y chayote est\u00e9n tiernos.", "Agrega 60g de frijoles cocidos; calienta 3 min y ajusta sal.", "Sirve el guiso caliente."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Ground Beef with Potato, Chayote and Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1132e846-401b-4adf-96f3-14f0f3bc133e'::uuid, _rid, 'carne molida de res (90% magra)', 130, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('35cb1f25-1e92-4e53-a0ac-b092f823b026'::uuid, _rid, 'papa', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3d2bfe65-32d5-40ea-b258-db7d2b852f4b'::uuid, _rid, 'chayote', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('44a0d5e8-1e58-45ee-b56f-ad60626c9845'::uuid, _rid, 'frijoles negros cocidos', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7c4ae76a-1bdd-4f08-8f96-1cb3bc7f2f8e'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a9a3e106-2053-430f-8765-d797129a4e85'::uuid, _rid, 'tomate', 50, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ab3063ca-80fc-430b-a21b-a8d8bf273aea'::uuid, _rid, 'cebolla blanca', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '7524df23-5620-4524-8f32-dd9b038d93d8'::uuid,
    'Beef Steak in Tomato Sauce with Rice', '{"es": "Bistec de res en salsa de tomate con arroz"}'::jsonb,
    'Bistec de res guisado en salsa de tomate natural con arroz blanco.', '{"es": "Bistec de res guisado en salsa de tomate natural con arroz blanco."}'::jsonb,
    490, 44, 31, 20, 2, 5, 440, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 150g de bistec de res en sart\u00e9n con aceite a fuego alto, 2 min por lado.", "Agrega 150g de tomate triturado, cebolla, ajo y or\u00e9gano; cocina 12 min.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min.", "Ajusta sal y pimienta en la salsa; a\u00f1ade perejil picado.", "Rebana el bistec en tiras.", "Sirve el bistec en salsa sobre el arroz."]'::jsonb))),
    '{"es": ["Dora 150g de bistec de res en sart\u00e9n con aceite a fuego alto, 2 min por lado.", "Agrega 150g de tomate triturado, cebolla, ajo y or\u00e9gano; cocina 12 min.", "Cocina 90g de arroz blanco en 180ml de agua con sal, 18 min.", "Ajusta sal y pimienta en la salsa; a\u00f1ade perejil picado.", "Rebana el bistec en tiras.", "Sirve el bistec en salsa sobre el arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak in Tomato Sauce with Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('febc8904-5801-4527-88ad-8cdf304716cb'::uuid, _rid, 'bistec de res', 150, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('764b19b4-2fd3-4787-8037-c3a92de25c4d'::uuid, _rid, 'tomate triturado', 150, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f12bf90b-757c-4e72-91d1-a721afc06ea3'::uuid, _rid, 'arroz blanco', 90, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0348c703-6977-4a47-a0ec-5cd1cfce41df'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('efcd48bf-163a-4b80-8da9-f1bbe9daf478'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('312b309a-a847-4366-9af6-0b02fc145ec9'::uuid, _rid, 'ajo', 5, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '07739334-e45e-48b3-967c-3c6218a2cd4b'::uuid,
    'Beef Tenderloin with Chickpeas, Bell Pepper and Rice', '{"es": "Lomo de res con garbanzos, pimientos y arroz"}'::jsonb,
    'Cena con lomo de res, garbanzos, pimientos coloridos y arroz.', '{"es": "Cena con lomo de res, garbanzos, pimientos coloridos y arroz."}'::jsonb,
    623, 49, 56, 22, 7, 4, 450, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de lomo de res con sal, p\u00e1prika y ajo; cocina en sart\u00e9n 4 min por lado.", "Saltea 80g de pimiento morr\u00f3n en tiras con cebolla y aceite, 4 min.", "Agrega 90g de garbanzos cocidos; sazona con comino, 3 min m\u00e1s.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min.", "Rebana el lomo.", "Sirve el lomo sobre el arroz con los garbanzos y pimientos."]'::jsonb))),
    '{"es": ["Sazona 140g de lomo de res con sal, p\u00e1prika y ajo; cocina en sart\u00e9n 4 min por lado.", "Saltea 80g de pimiento morr\u00f3n en tiras con cebolla y aceite, 4 min.", "Agrega 90g de garbanzos cocidos; sazona con comino, 3 min m\u00e1s.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min.", "Rebana el lomo.", "Sirve el lomo sobre el arroz con los garbanzos y pimientos."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Tenderloin with Chickpeas, Bell Pepper and Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a55a31d8-1722-48e7-a359-0e3d55b0e382'::uuid, _rid, 'lomo de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('dd2f881f-ad32-4729-b3a8-969bcecf3adf'::uuid, _rid, 'garbanzos cocidos', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ccac0e54-3749-42c5-ae7b-2fced2644c58'::uuid, _rid, 'pimiento morrón', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('4bd0ada6-6ffe-4160-acef-606c0a965124'::uuid, _rid, 'arroz blanco', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9951b60b-20db-4a8b-87f5-13252c4a4be7'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7a5b2b18-2740-4b59-bca7-388585859590'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fb625705-78ba-491b-bcae-c97a2cea1b57'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '79e27705-2cc8-4b51-a7e2-47f2de11903d'::uuid,
    'Ground Beef with Corn, Green Beans and Rice', '{"es": "Carne molida de res con ma\u00edz, ejotes y arroz"}'::jsonb,
    'Cena con carne molida de res, maíz tierno, ejotes y arroz blanco.', '{"es": "Cena con carne molida de res, ma\u00edz tierno, ejotes y arroz blanco."}'::jsonb,
    553, 41, 51, 20, 4, 4, 440, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 130g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega 90g de ma\u00edz tierno cocido, 80g de ejotes blanqueados y sofrito de cebolla.", "Sazona con comino, ajo en polvo y sal; cocina 4 min m\u00e1s.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min.", "Blanquea los ejotes previamente 4 min en agua hirviendo con sal.", "Sirve la mezcla de carne sobre el arroz."]'::jsonb))),
    '{"es": ["Dora 130g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega 90g de ma\u00edz tierno cocido, 80g de ejotes blanqueados y sofrito de cebolla.", "Sazona con comino, ajo en polvo y sal; cocina 4 min m\u00e1s.", "Cocina 80g de arroz blanco en 160ml de agua con sal, 18 min.", "Blanquea los ejotes previamente 4 min en agua hirviendo con sal.", "Sirve la mezcla de carne sobre el arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Ground Beef with Corn, Green Beans and Rice';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('c8aedf85-276f-43e3-b8f5-ff4ea6db75e4'::uuid, _rid, 'carne molida de res (90% magra)', 130, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('cb4c8a18-df6d-4f92-9113-fe62414785d1'::uuid, _rid, 'maíz tierno', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('965a6e5e-2c4e-4296-aff6-698ae7a4cdb1'::uuid, _rid, 'ejotes', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('12bfe0e4-47ca-4d15-b4a1-a926b1aab684'::uuid, _rid, 'arroz blanco', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e2f68f25-7066-400a-a72f-5418d24b81e6'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3868be63-abdd-49e8-b4d1-150ba032c183'::uuid, _rid, 'cebolla blanca', 30, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '5c434ae9-78ee-4b19-ac2f-f2046d697773'::uuid,
    'Beef Steak with Sweet Potato and Broccoli', '{"es": "Bistec de res con camote y br\u00f3coli"}'::jsonb,
    'Cena con bistec de res a la plancha, camote cocido y brócoli.', '{"es": "Cena con bistec de res a la plancha, camote cocido y br\u00f3coli."}'::jsonb,
    495, 44, 36, 21, 5, 5, 420, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 145g de bistec de res con sal, pimienta y ajo en polvo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Hierve 120g de camote en cubos en agua con sal, 15 min; escurre.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min.", "Saltea el br\u00f3coli y el camote con aceite y ajo, 3 min.", "Rebana el bistec; sirve con el camote y el br\u00f3coli."]'::jsonb))),
    '{"es": ["Sazona 145g de bistec de res con sal, pimienta y ajo en polvo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Hierve 120g de camote en cubos en agua con sal, 15 min; escurre.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min.", "Saltea el br\u00f3coli y el camote con aceite y ajo, 3 min.", "Rebana el bistec; sirve con el camote y el br\u00f3coli."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak with Sweet Potato and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f4661aa4-24d3-4c37-b1b7-d15d4734e1fe'::uuid, _rid, 'bistec de res', 145, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f2ae7977-e865-4352-8d8d-d0b1b759362c'::uuid, _rid, 'camote', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7eb246ef-c619-4de6-9d67-3832e0feeb8a'::uuid, _rid, 'brócoli', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('812b3ab8-8f04-4028-8316-59051ec80c53'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('04969696-0232-40bb-9ae4-d3a955109e7b'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f7e4711d-108e-4d58-8798-8660654f1582'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '62746d4b-7147-4711-b2ab-83ca9a2aed89'::uuid,
    'Beef Tenderloin with Brown Rice and Lentils', '{"es": "Lomo de res con arroz integral y lentejas"}'::jsonb,
    'Cena con lomo de res, arroz integral y lentejas cocidas.', '{"es": "Cena con lomo de res, arroz integral y lentejas cocidas."}'::jsonb,
    500, 43, 39, 17, 8, 3, 410, 6,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de lomo de res con sal, pimienta y ajo; cocina en sart\u00e9n 4 min por lado.", "Cocina 90g de arroz integral en 200ml de agua con sal, 30 min.", "Hierve 80g de lentejas en agua con sal, ajo y laurel, 20 min; escurre.", "Sofr\u00ede cebolla y tomate con aceite 3 min; agrega las lentejas.", "Rebana el lomo.", "Sirve el lomo con el arroz integral y las lentejas."]'::jsonb))),
    '{"es": ["Sazona 140g de lomo de res con sal, pimienta y ajo; cocina en sart\u00e9n 4 min por lado.", "Cocina 90g de arroz integral en 200ml de agua con sal, 30 min.", "Hierve 80g de lentejas en agua con sal, ajo y laurel, 20 min; escurre.", "Sofr\u00ede cebolla y tomate con aceite 3 min; agrega las lentejas.", "Rebana el lomo.", "Sirve el lomo con el arroz integral y las lentejas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Tenderloin with Brown Rice and Lentils';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8c8335b9-04a2-4e44-99fe-89e14e7d772c'::uuid, _rid, 'lomo de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('31d9096f-ca6f-4d9e-a764-a758b0c564c8'::uuid, _rid, 'arroz integral', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3c8bbae2-b549-437b-8408-79b8edaa7fa1'::uuid, _rid, 'lentejas cocidas', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('aee8ccc0-6f18-4a71-b5b1-2bf92d140edd'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b3253576-5886-4716-90c5-594e51b1ad92'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e3b303c0-91ee-40e3-bade-9e063ede98c1'::uuid, _rid, 'tomate', 30, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '3f16b772-88ce-4dc8-9ffb-3c9cda4c03d3'::uuid,
    'Ground Beef with Beans and Corn Tortillas', '{"es": "Carne molida de res con frijoles y tortillas de ma\u00edz"}'::jsonb,
    'Cena con carne molida de res, frijoles negros y tortillas de maíz.', '{"es": "Cena con carne molida de res, frijoles negros y tortillas de ma\u00edz."}'::jsonb,
    579, 46, 54, 18, 8, 3, 450, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 130g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega cebolla, ajo, tomate picados y comino; sofr\u00ede 4 min.", "Calienta 90g de frijoles negros con sofrito de tomate y cebolla, 4 min.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Sazona la carne molida y ajusta la sal.", "Sirve la carne molida con frijoles sobre las tortillas."]'::jsonb))),
    '{"es": ["Dora 130g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega cebolla, ajo, tomate picados y comino; sofr\u00ede 4 min.", "Calienta 90g de frijoles negros con sofrito de tomate y cebolla, 4 min.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Sazona la carne molida y ajusta la sal.", "Sirve la carne molida con frijoles sobre las tortillas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Ground Beef with Beans and Corn Tortillas';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ce2a5cc4-08fb-4984-aadd-fa332aa9040d'::uuid, _rid, 'carne molida de res (90% magra)', 130, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b76b00eb-9edd-480b-8202-25b23dd7a1cb'::uuid, _rid, 'frijoles negros cocidos', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('0f9582fc-51cd-42d1-95a1-95123d48f4ef'::uuid, _rid, 'tortilla de maíz', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f6b5300c-46f9-483b-8274-6f3ed3e757b6'::uuid, _rid, 'aceite de oliva', 3, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b903f40a-9fc7-4b39-9f63-d9b350751b04'::uuid, _rid, 'tomate', 50, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('56d9aafb-3064-43bb-9eb1-8332cef537e4'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'd8c7ae87-b38d-4829-8661-ae4be1e2337c'::uuid,
    'Beef Steak with Potato, Carrot and Green Beans', '{"es": "Bistec de res con papa, zanahoria y ejotes"}'::jsonb,
    'Cena con bistec de res a la plancha, papa, zanahoria y ejotes.', '{"es": "Cena con bistec de res a la plancha, papa, zanahoria y ejotes."}'::jsonb,
    495, 42, 39, 20, 5, 4, 420, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de bistec de res con sal, pimienta y ajo en polvo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Hierve 120g de papa en cubos y 60g de zanahoria en rodajas en agua con sal, 15 min.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea papa, zanahoria y ejotes con aceite y cebolla, 3 min.", "Rebana el bistec; sirve con las verduras."]'::jsonb))),
    '{"es": ["Sazona 140g de bistec de res con sal, pimienta y ajo en polvo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Hierve 120g de papa en cubos y 60g de zanahoria en rodajas en agua con sal, 15 min.", "Blanquea 80g de ejotes en agua hirviendo con sal, 4 min.", "Saltea papa, zanahoria y ejotes con aceite y cebolla, 3 min.", "Rebana el bistec; sirve con las verduras."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak with Potato, Carrot and Green Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('7ed5eb6f-c5a7-4a8e-be1f-457988920816'::uuid, _rid, 'bistec de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9c820f25-69d4-4fa7-bd44-00baeb571c6a'::uuid, _rid, 'papa', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('61ad36ea-1ebe-4f75-824c-951adeeb5243'::uuid, _rid, 'zanahoria', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('a5043f2a-3ec0-419c-97a7-df562e631ed3'::uuid, _rid, 'ejotes', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('b0d25d3b-4277-45fc-ad73-7103601ca41d'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('8610a829-7a98-431e-8143-5952e400828d'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '802fe74b-f696-4af1-8cac-8e0ffd92ac54'::uuid,
    'Stewed Beef Tenderloin with Lentils, Potato and Carrot', '{"es": "Lomo de res guisado con lentejas, papa y zanahoria"}'::jsonb,
    'Guiso de lomo de res con lentejas, papa y zanahoria.', '{"es": "Guiso de lomo de res con lentejas, papa y zanahoria."}'::jsonb,
    549, 48, 45, 21, 9, 4, 450, 7,
    'dinner'::meal_time_enum, 35,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Corta 140g de lomo de res en cubos; dora con aceite y ajo en sart\u00e9n, 3 min.", "Agrega cebolla y tomate picados; sofr\u00ede 3 min.", "A\u00f1ade 80g de lentejas, 100g de papa y 60g de zanahoria en cubos con 500ml de agua.", "Hierve, luego cocina a fuego medio 20 min hasta que todo est\u00e9 tierno.", "Ajusta sal, a\u00f1ade comino y cilantro fresco.", "Sirve el guiso caliente."]'::jsonb))),
    '{"es": ["Corta 140g de lomo de res en cubos; dora con aceite y ajo en sart\u00e9n, 3 min.", "Agrega cebolla y tomate picados; sofr\u00ede 3 min.", "A\u00f1ade 80g de lentejas, 100g de papa y 60g de zanahoria en cubos con 500ml de agua.", "Hierve, luego cocina a fuego medio 20 min hasta que todo est\u00e9 tierno.", "Ajusta sal, a\u00f1ade comino y cilantro fresco.", "Sirve el guiso caliente."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Stewed Beef Tenderloin with Lentils, Potato and Carrot';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('08a1f22b-2646-4bb7-873e-115787a69972'::uuid, _rid, 'lomo de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bb24a0d2-9630-4a0c-97d6-0176c2f124f8'::uuid, _rid, 'lentejas', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('e2271c6e-44c3-48e8-a419-df00195ce8e9'::uuid, _rid, 'papa', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9b561a72-5058-4619-a0fc-2d7bb3f0c0ec'::uuid, _rid, 'zanahoria', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bb186530-4ffc-478a-a79a-a04ec67ed605'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d96341b4-3958-4610-9096-9410c12ac341'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5f52d709-6cf3-4ede-800d-4347bb7b9709'::uuid, _rid, 'tomate', 30, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'ef8c24d0-6dad-4b7e-b481-9b264026a654'::uuid,
    'Ground Beef with Rice, Bell Pepper and Onion', '{"es": "Carne molida de res con arroz, pimientos y cebolla"}'::jsonb,
    'Cena con carne molida de res, arroz blanco, pimientos y cebolla.', '{"es": "Cena con carne molida de res, arroz blanco, pimientos y cebolla."}'::jsonb,
    530, 40, 44, 21, 3, 4, 440, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 135g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega 80g de pimiento y 80g de cebolla en tiras; saltea 4 min.", "Sazona con sal, ajo en polvo y or\u00e9gano; cocina 3 min m\u00e1s.", "Cocina 100g de arroz blanco en 200ml de agua con sal, 18 min.", "Agrega 50g de tomate picado a la carne; calienta 2 min.", "Sirve la carne molida con verduras sobre el arroz."]'::jsonb))),
    '{"es": ["Dora 135g de carne molida en sart\u00e9n con aceite, 8 min rompi\u00e9ndola.", "Agrega 80g de pimiento y 80g de cebolla en tiras; saltea 4 min.", "Sazona con sal, ajo en polvo y or\u00e9gano; cocina 3 min m\u00e1s.", "Cocina 100g de arroz blanco en 200ml de agua con sal, 18 min.", "Agrega 50g de tomate picado a la carne; calienta 2 min.", "Sirve la carne molida con verduras sobre el arroz."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Ground Beef with Rice, Bell Pepper and Onion';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3a65f96e-cecf-48f7-a64c-9403a0c6d967'::uuid, _rid, 'carne molida de res (90% magra)', 135, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('dc0b2b03-811d-45e0-a1a5-8f4ffa679642'::uuid, _rid, 'pimiento morrón', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('659852ea-ddcc-4a16-adfb-ee5ce350276a'::uuid, _rid, 'cebolla blanca', 80, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('89b582e4-8f74-41e0-a92b-9eb2842dd56f'::uuid, _rid, 'arroz blanco', 100, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2a05d053-1841-4eab-b4b6-944be383fb78'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('bc30d638-cbb3-4c70-9454-d27420b702b8'::uuid, _rid, 'tomate', 50, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    'eb39458f-6c6a-403e-8a8a-0ad1d762894a'::uuid,
    'Beef Steak with Quinoa, Chickpeas and Spinach', '{"es": "Bistec de res con quinoa, garbanzos y espinacas"}'::jsonb,
    'Cena con bistec de res, quinoa, garbanzos y espinacas.', '{"es": "Cena con bistec de res, quinoa, garbanzos y espinacas."}'::jsonb,
    556, 48, 42, 22, 8, 3, 440, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 135g de bistec de res con sal, pimienta y ajo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Cocina 90g de quinoa en 180ml de agua con sal, 15 min.", "Sofr\u00ede 60g de garbanzos con cebolla y ajo en aceite 3 min.", "Saltea 80g de espinacas con los garbanzos, 2 min.", "Rebana el bistec; sirve sobre la quinoa con garbanzos y espinacas."]'::jsonb))),
    '{"es": ["Sazona 135g de bistec de res con sal, pimienta y ajo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Cocina 90g de quinoa en 180ml de agua con sal, 15 min.", "Sofr\u00ede 60g de garbanzos con cebolla y ajo en aceite 3 min.", "Saltea 80g de espinacas con los garbanzos, 2 min.", "Rebana el bistec; sirve sobre la quinoa con garbanzos y espinacas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak with Quinoa, Chickpeas and Spinach';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3ce39ab4-9607-4aea-91a4-e49a987a758d'::uuid, _rid, 'bistec de res', 135, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5d2fd8b1-32fd-4dbb-826e-2630d931bedc'::uuid, _rid, 'quinoa', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('408e72e6-3969-480a-bc23-56158a707fa3'::uuid, _rid, 'garbanzos cocidos', 60, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('af9428fb-4eb7-4334-816b-8e915e48b9ef'::uuid, _rid, 'espinacas', 80, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2f849b90-4807-4c0d-ae11-6edf36d6222e'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('85172f22-f92d-4006-8181-29cde423fe49'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('f1d7255b-6c40-47a6-bea0-64ffc3be2487'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '70459771-216a-40f9-992f-9b55d5e43c94'::uuid,
    'Beef Tenderloin with Yuca and Chayote', '{"es": "Lomo de res con yuca y chayote"}'::jsonb,
    'Cena con lomo de res, yuca cocida, chayote y frijoles.', '{"es": "Cena con lomo de res, yuca cocida, chayote y frijoles."}'::jsonb,
    592, 45, 58, 21, 4, 4, 430, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 140g de lomo de res con sal, ajo y or\u00e9gano; cocina en sart\u00e9n 4 min por lado.", "Pela 90g de yuca; hierve en agua con sal 20 min hasta suavizar.", "Hierve 100g de chayote en cubos en agua con sal, 10 min.", "Calienta 60g de frijoles negros con sofrito de cebolla y tomate.", "Sofr\u00ede la yuca en trozos con aceite y ajo, 3 min para dorar.", "Sirve el lomo con la yuca, el chayote y los frijoles."]'::jsonb))),
    '{"es": ["Sazona 140g de lomo de res con sal, ajo y or\u00e9gano; cocina en sart\u00e9n 4 min por lado.", "Pela 90g de yuca; hierve en agua con sal 20 min hasta suavizar.", "Hierve 100g de chayote en cubos en agua con sal, 10 min.", "Calienta 60g de frijoles negros con sofrito de cebolla y tomate.", "Sofr\u00ede la yuca en trozos con aceite y ajo, 3 min para dorar.", "Sirve el lomo con la yuca, el chayote y los frijoles."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Tenderloin with Yuca and Chayote';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fd593f5c-2fdf-414b-a6a6-50b8bae6e42d'::uuid, _rid, 'lomo de res', 140, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('163e5da0-9c6f-4480-bdb5-4299363ae999'::uuid, _rid, 'yuca', 90, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('17c546fb-c29c-4ac5-b3e2-aa2466a4d4cd'::uuid, _rid, 'chayote', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1950afe0-f9da-4a3d-b5ea-2cd31465a981'::uuid, _rid, 'frijoles negros cocidos', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('13ff47d6-3e2b-4ee6-8e56-fc5288b7e7aa'::uuid, _rid, 'aceite de oliva', 4, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('3d0506f5-e712-41f6-9860-21682818da9e'::uuid, _rid, 'cebolla blanca', 30, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('d1024950-b20a-4ff8-a358-4d5126d091a1'::uuid, _rid, 'ajo', 5, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '8f620ed7-4805-41cf-8f50-0056e9d597b4'::uuid,
    'Ground Beef with Corn, Beans and Corn Tortillas', '{"es": "Carne molida de res con ma\u00edz, frijoles y tortillas de ma\u00edz"}'::jsonb,
    'Cena con carne molida de res, maíz, frijoles y tortillas de maíz.', '{"es": "Cena con carne molida de res, ma\u00edz, frijoles y tortillas de ma\u00edz."}'::jsonb,
    615, 45, 65, 18, 8, 4, 450, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Dora 125g de carne molida en sart\u00e9n con aceite, 8 min.", "Agrega sofrito de cebolla, ajo y tomate; sazona con comino, 3 min.", "Incorpora 80g de ma\u00edz tierno y 70g de frijoles negros cocidos; calienta 3 min.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Ajusta sal y agrega cilantro picado.", "Sirve la carne molida con ma\u00edz y frijoles sobre las tortillas."]'::jsonb))),
    '{"es": ["Dora 125g de carne molida en sart\u00e9n con aceite, 8 min.", "Agrega sofrito de cebolla, ajo y tomate; sazona con comino, 3 min.", "Incorpora 80g de ma\u00edz tierno y 70g de frijoles negros cocidos; calienta 3 min.", "Calienta 2 tortillas de ma\u00edz (60g) en comal seco 1 min por lado.", "Ajusta sal y agrega cilantro picado.", "Sirve la carne molida con ma\u00edz y frijoles sobre las tortillas."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Ground Beef with Corn, Beans and Corn Tortillas';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9e4d5323-b214-4cb8-a172-b754723ca756'::uuid, _rid, 'carne molida de res (90% magra)', 125, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('136de713-b905-41cc-a5f6-fb2eb18455d4'::uuid, _rid, 'maíz tierno', 80, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('13b83747-eff9-43e3-be21-1ad71b7e3259'::uuid, _rid, 'frijoles negros cocidos', 70, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('01824e63-2e3d-461b-8bc2-db47332b77de'::uuid, _rid, 'tortilla de maíz', 60, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fc864638-5b21-4523-a7b1-ca3569fd7773'::uuid, _rid, 'aceite de oliva', 3, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('26578bb4-f0bc-4952-9bf5-257601adeacb'::uuid, _rid, 'tomate', 40, 6);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 7;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('35c0f158-d762-4cf3-8de6-8ff2053ebe51'::uuid, _rid, 'cebolla blanca', 20, 7);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '77d0ec02-0015-4f8b-86d6-2a3a3392ab50'::uuid,
    'Beef Steak with Cactus and Black Beans', '{"es": "Bistec de res con nopales y frijoles negros"}'::jsonb,
    'Cena mexicana con bistec de res, nopales y frijoles negros.', '{"es": "Cena mexicana con bistec de res, nopales y frijoles negros."}'::jsonb,
    492, 49, 30, 21, 10, 3, 420, 7,
    'dinner'::meal_time_enum, 25,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Sazona 145g de bistec de res con sal, pimienta y ajo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Lava y trocea 100g de nopales; cocina en sart\u00e9n seca con sal 5 min.", "Calienta 90g de frijoles negros con sofrito de cebolla y tomate, 4 min.", "Mezcla los nopales con los frijoles; sazona con comino.", "Rebana el bistec; sirve con los nopales y frijoles."]'::jsonb))),
    '{"es": ["Sazona 145g de bistec de res con sal, pimienta y ajo.", "Cocina en plancha caliente con aceite, 4 min por lado.", "Lava y trocea 100g de nopales; cocina en sart\u00e9n seca con sal 5 min.", "Calienta 90g de frijoles negros con sofrito de cebolla y tomate, 4 min.", "Mezcla los nopales con los frijoles; sazona con comino.", "Rebana el bistec; sirve con los nopales y frijoles."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Beef Steak with Cactus and Black Beans';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('2d526d15-6972-4275-ba07-1d3bae4be56b'::uuid, _rid, 'bistec de res', 145, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1b7c9d4c-258b-49c3-ab31-e0b8dc6da2da'::uuid, _rid, 'nopales', 100, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9164a7f3-daa5-49f4-95ed-34454dbbed85'::uuid, _rid, 'frijoles negros cocidos', 90, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('fadffbbb-d5fe-40ab-b551-7fb1f4c769a6'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5f12f79a-3d62-476b-bf2e-8790116555a3'::uuid, _rid, 'cebolla blanca', 30, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('ade50d8f-54fa-4ce2-a2d5-39a8e311ac6e'::uuid, _rid, 'tomate', 30, 6);
END$$;
DO $$
DECLARE _rid uuid;
BEGIN
  INSERT INTO recipes (
    id, name_en, name_translations, description_en, description_translations,
    kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, sat_fat_g,
    meal_time, prep_min, instructions_en, instructions_translations,
    allergens, tags, regions, is_vegan, is_vegetarian, contains_meat, source_batch
  ) VALUES (
    '96d36eaa-a5e1-4507-9eba-56987a89a579'::uuid,
    'Roasted Beef Tenderloin with Sweet Potato and Broccoli', '{"es": "Lomo de res al horno con camote y br\u00f3coli"}'::jsonb,
    'Lomo de res al horno con camote y brócoli al vapor.', '{"es": "Lomo de res al horno con camote y br\u00f3coli al vapor."}'::jsonb,
    513, 46, 37, 21, 5, 5, 430, 7,
    'dinner'::meal_time_enum, 30,
    (SELECT ARRAY(SELECT jsonb_array_elements_text('["Precalienta horno a 200\u00b0C. Sazona 150g de lomo de res con sal, romero y ajo.", "Hornea 20-25 min hasta temperatura interna de 60\u00b0C para t\u00e9rmino medio.", "Hierve 120g de camote en cubos en agua con sal, 15 min; escurre.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min.", "Saltea el camote y br\u00f3coli con aceite y ajo, 3 min.", "Rebana el lomo; sirve con el camote y el br\u00f3coli."]'::jsonb))),
    '{"es": ["Precalienta horno a 200\u00b0C. Sazona 150g de lomo de res con sal, romero y ajo.", "Hornea 20-25 min hasta temperatura interna de 60\u00b0C para t\u00e9rmino medio.", "Hierve 120g de camote en cubos en agua con sal, 15 min; escurre.", "Blanquea 100g de br\u00f3coli en agua hirviendo con sal, 4 min.", "Saltea el camote y br\u00f3coli con aceite y ajo, 3 min.", "Rebana el lomo; sirve con el camote y el br\u00f3coli."]}'::jsonb,
    ARRAY[]::allergen_enum[], ARRAY['high_protein', 'beef', 'beef']::text[], ARRAY['latam', 'world']::char(5)[],
    FALSE, FALSE, TRUE, 'nova_pork_beef_v1'
  )
  ON CONFLICT (name_en) DO UPDATE SET
    name_translations        = EXCLUDED.name_translations,
    description_en           = EXCLUDED.description_en,
    description_translations = EXCLUDED.description_translations,
    kcal=EXCLUDED.kcal, protein_g=EXCLUDED.protein_g,
    carbs_g=EXCLUDED.carbs_g, fat_g=EXCLUDED.fat_g,
    fiber_g=EXCLUDED.fiber_g, sugar_g=EXCLUDED.sugar_g,
    sodium_mg=EXCLUDED.sodium_mg, sat_fat_g=EXCLUDED.sat_fat_g,
    meal_time=EXCLUDED.meal_time, prep_min=EXCLUDED.prep_min,
    tags=EXCLUDED.tags, regions=EXCLUDED.regions,
    is_vegan=EXCLUDED.is_vegan, is_vegetarian=EXCLUDED.is_vegetarian,
    contains_meat=EXCLUDED.contains_meat, source_batch=EXCLUDED.source_batch
  RETURNING id INTO _rid;
  IF _rid IS NULL THEN
    SELECT id INTO _rid FROM recipes WHERE name_en = 'Roasted Beef Tenderloin with Sweet Potato and Broccoli';
  END IF;
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 1;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('37d123b4-7765-4243-9d1f-13dee0d9ea61'::uuid, _rid, 'lomo de res', 150, 1);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 2;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('6ef6756e-faef-43fd-8f95-2d854178c5ce'::uuid, _rid, 'camote', 120, 2);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 3;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('5c29cc81-1aa3-494b-ab47-766463fe218a'::uuid, _rid, 'brócoli', 100, 3);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 4;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('9aa1015b-32d5-4692-be8d-5f7b91c1ba74'::uuid, _rid, 'aceite de oliva', 4, 4);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 5;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('624fe739-33a3-45c6-8ef9-7d962560fde5'::uuid, _rid, 'ajo', 5, 5);
  DELETE FROM recipe_components WHERE recipe_id = _rid AND position = 6;
  INSERT INTO recipe_components (id, recipe_id, free_text_name, amount_g, position)
  VALUES ('1c38f621-b2eb-4706-ad10-b2e747225acc'::uuid, _rid, 'cebolla blanca', 20, 6);
END$$;