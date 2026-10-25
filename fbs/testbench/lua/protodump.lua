-- fbs prototype dump: writes script-output/fbs-prototypes.json on the first tick.
-- Generated into a temporary mod by `fbs protos`.

local function box(b)
  if not b then return nil end
  return {b.left_top.x, b.left_top.y, b.right_bottom.x, b.right_bottom.y}
end

local function vec(v)
  if not v then return nil end
  local x, y = v.x or v[1], v.y or v[2]
  if x == nil then return nil end
  return {x, y}
end

local function try(f, ...)
  local ok, v = pcall(f, ...)
  if ok then return v end
  return nil
end

local function dump()
  local out = {entities = {}, recipes = {}, items = {}, qualities = {}, fluids = {}, version = script.active_mods["base"]}
  local normal = prototypes.quality["normal"]

  for name, p in pairs(prototypes.entity) do
    local e = {
      type = p.type,
      tile_width = p.tile_width,
      tile_height = p.tile_height,
      collision_box = box(p.collision_box),
      module_slots = p.module_inventory_size,
      flags = try(function() return p.flags end),
    }
    if p.fluidbox_prototypes and #p.fluidbox_prototypes > 0 then
      e.fluidboxes = {}
      for _, fb in ipairs(p.fluidbox_prototypes) do
        local conns = {}
        for _, c in ipairs(fb.pipe_connections or {}) do
          local pos = vec(c.positions and c.positions[1] or c.position)
          conns[#conns + 1] = {
            position = pos,
            direction = c.direction,
            type = c.connection_type,
            flow = c.flow_direction,
            max_underground_distance = c.max_underground_distance,
          }
        end
        e.fluidboxes[#e.fluidboxes + 1] = {production_type = fb.production_type, connections = conns}
      end
    end
    e.crafting_speed = try(function() return p.get_crafting_speed(normal) end)
    e.crafting_categories = try(function() local t = {} for k in pairs(p.crafting_categories or {}) do t[#t + 1] = k end return t end)
    e.vector_to_place_result = try(function() return vec(p.vector_to_place_result) end)
    e.supply_area_distance = try(function() return p.get_supply_area_distance(normal) end)
    e.max_wire_distance = try(function() return p.get_max_wire_distance(normal) end)
    e.logistic_radius = try(function() return p.get_logistic_radius(normal) end)
    e.construction_radius = try(function() return p.get_construction_radius(normal) end)
    e.inserter_pickup_position = try(function() return vec(p.inserter_pickup_position) end)
    e.inserter_drop_position = try(function() return vec(p.inserter_drop_position) end)
    e.belt_speed = try(function() return p.belt_speed end)
    e.max_underground_distance = try(function() return p.max_underground_distance end)
    e.effect_receiver = try(function() return p.effect_receiver end)
    e.allowed_effects = try(function() return p.allowed_effects end)
    out.entities[name] = e
  end

  for name, r in pairs(prototypes.recipe) do
    local ing, prod = {}, {}
    for _, i in ipairs(r.ingredients) do ing[#ing + 1] = {type = i.type, name = i.name, amount = i.amount} end
    for _, i in ipairs(r.products) do
      prod[#prod + 1] = {type = i.type, name = i.name, amount = i.amount, amount_min = i.amount_min, amount_max = i.amount_max,
        probability = i.probability, extra_count_fraction = i.extra_count_fraction}
    end
    out.recipes[name] = {
      category = try(function() return r.category end),
      categories = try(function() local t = {} for k, v in pairs(r.categories or {}) do t[#t + 1] = type(k) == "string" and k or v end return t end),
      energy = r.energy,
      ingredients = ing,
      products = prod,
      allow_quality = try(function() return r.allow_quality end),
      allow_productivity = try(function() return r.allow_productivity end),
      maximum_productivity = try(function() return r.maximum_productivity end),
      hidden = try(function() return r.hidden end),
    }
  end

  for name, it in pairs(prototypes.item) do
    local i = {type = it.type, stack_size = it.stack_size, place_result = try(function() return it.place_result and it.place_result.name end)}
    if it.type == "module" then
      i.module_effects = try(function() return it.module_effects end)
      i.category = try(function() return it.category end)
      i.tier = try(function() return it.tier end)
    end
    out.items[name] = i
  end

  for name, q in pairs(prototypes.quality) do
    out.qualities[name] = {level = q.level, next = q.next and q.next.name or nil, next_probability = try(function() return q.next_probability end), hidden = try(function() return q.hidden end)}
  end

  for name, f in pairs(prototypes.fluid) do
    out.fluids[name] = {default_temperature = f.default_temperature}
  end

  helpers.write_file("fbs-prototypes.json", helpers.table_to_json(out), false)
  log("[fbs] PROTODUMP DONE")
end

local done = false
script.on_event(defines.events.on_tick, function()
  if done then return end
  done = true
  local ok, err = pcall(dump)
  if not ok then log("[fbs] PROTODUMP ERROR " .. tostring(err)) end
end)
