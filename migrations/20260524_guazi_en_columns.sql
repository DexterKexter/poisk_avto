-- New columns for en.guazi.com detail data and general enrichment.
-- Many of these fields were previously buried in source_data JSON.

-- Inspection
ALTER TABLE cars ADD COLUMN IF NOT EXISTS inspection_grade text;

-- EV / Battery
ALTER TABLE cars ADD COLUMN IF NOT EXISTS ev_range_km numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS battery_type text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS energy_consumption numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS charge_time_fast text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS charge_time_slow text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS front_motor_power_kw numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS front_motor_torque_nm numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS rear_motor_power_kw numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS rear_motor_torque_nm numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS total_motor_torque_nm numeric;

-- Engine details
ALTER TABLE cars ADD COLUMN IF NOT EXISTS engine_model text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS num_cylinders integer;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS cylinder_arrangement text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS valves_per_cylinder integer;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS valve_train text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS torque_nm numeric;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS power_rpm text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS torque_rpm text;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS fuel_consumption numeric;

-- Body / dimensions
ALTER TABLE cars ADD COLUMN IF NOT EXISTS curb_weight_kg integer;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS doors integer;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS seats integer;

-- Dates / logistics
ALTER TABLE cars ADD COLUMN IF NOT EXISTS mfg_date date;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS port text;

-- Damage flags
ALTER TABLE cars ADD COLUMN IF NOT EXISTS no_water_damage boolean;
ALTER TABLE cars ADD COLUMN IF NOT EXISTS no_fire_damage boolean;

-- Indexes for common filter columns
CREATE INDEX IF NOT EXISTS idx_cars_inspection_grade ON cars(inspection_grade);
CREATE INDEX IF NOT EXISTS idx_cars_ev_range ON cars(ev_range_km) WHERE ev_range_km IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cars_battery_kwh ON cars(battery_kwh) WHERE battery_kwh IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cars_curb_weight ON cars(curb_weight_kg) WHERE curb_weight_kg IS NOT NULL;

COMMENT ON COLUMN cars.inspection_grade IS 'Inspection quality grade: A/B/C/D/S (en.guazi), 优秀/良好/一般 (CN guazi)';
COMMENT ON COLUMN cars.ev_range_km IS 'EV range in km (NEDC/CLTC/WLTP)';
COMMENT ON COLUMN cars.energy_consumption IS 'kWh/100km for EV';
COMMENT ON COLUMN cars.fuel_consumption IS 'L/100km for ICE (WLTC/NEDC)';
COMMENT ON COLUMN cars.mfg_date IS 'Manufacturing date (month-level), separate from reg_date';
COMMENT ON COLUMN cars.port IS 'FOB port for export pricing (e.g. Shanghai)';
