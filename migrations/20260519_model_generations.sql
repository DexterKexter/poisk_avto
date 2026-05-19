-- model_generations: catalog of model generations (BMW 3-series F30, Audi A4 B9, etc.)
-- Loaded from data/model_generations.json (2516 rows) + manual Chinese EV / Korean alias additions.
-- cars.generation_id is backfilled by year-range matching.

CREATE TABLE IF NOT EXISTS public.model_generations (
  id           BIGSERIAL PRIMARY KEY,
  brand_name   TEXT NOT NULL,
  model_name   TEXT NOT NULL,
  gen          INTEGER NOT NULL,
  full_name    TEXT NOT NULL,
  start_year   INTEGER,
  end_year     INTEGER,
  source       TEXT NOT NULL DEFAULT 'gen_json',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT model_generations_unique UNIQUE (brand_name, model_name, gen, full_name)
);

CREATE INDEX IF NOT EXISTS idx_model_gen_lookup
  ON public.model_generations (lower(brand_name), lower(model_name));
CREATE INDEX IF NOT EXISTS idx_model_gen_year
  ON public.model_generations (start_year, end_year);

ALTER TABLE public.cars
  ADD COLUMN IF NOT EXISTS generation_id BIGINT REFERENCES public.model_generations(id);
CREATE INDEX IF NOT EXISTS idx_cars_generation
  ON public.cars (generation_id) WHERE generation_id IS NOT NULL;

COMMENT ON TABLE public.model_generations IS
  'Catalog of car model generations with year ranges (e.g. BMW 5-series G30 2017-2024). Loaded from data/model_generations.json + manual zh-EV/ko-alias additions.';
COMMENT ON COLUMN public.model_generations.end_year IS 'NULL = current generation, still in production';
COMMENT ON COLUMN public.cars.generation_id IS 'Matched generation by brand+model+year. NULL when no catalog entry covers the year.';
