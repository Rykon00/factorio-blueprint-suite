-- fbs testbench: builds a blueprint on a fresh lab surface, powers it, runs it
-- and records what happens. The Python side prepends `local FBS_CONFIG_JSON = [=[...]=]`.

local CFG = helpers.json_to_table(FBS_CONFIG_JSON)
local SURFACE = CFG.surface_name or "fbs-lab"
local REPORT_FILE = CFG.report_file or "fbs-report.json"

local status_name = {}
for k, v in pairs(defines.entity_status) do status_name[v] = k end

local WORKING = {working = true, normal = true}
local CRAFTER_TYPES = {"assembling-machine", "furnace", "mining-drill", "lab", "rocket-silo"}
local CONTAINER_TYPES = {"container", "logistic-container"}

local state = {
  phase = "init",
  start_tick = nil,
  report = {config = CFG, problems = {}, samples = {}, build = {}},
  crafters = {},   -- unit_number -> {entity, counts}
}

local function problem(msg)
  local p = state.report.problems
  p[#p + 1] = msg
  log("[fbs] PROBLEM " .. msg)
end

local function write_report()
  helpers.write_file(REPORT_FILE, helpers.table_to_json(state.report), false)
end

local function qualities()
  local chain, q = {}, prototypes.quality["normal"]
  while q do
    chain[#chain + 1] = q.name
    q = q.next
  end
  return chain
end
local QUALITIES = qualities()

-- ---------------------------------------------------------------- surface
local function prepare_surface()
  local surface = game.surfaces[SURFACE]
  if not surface then
    local mgs = {
      default_enable_all_autoplace_controls = false,
      autoplace_settings = {entity = {treat_missing_as_default = false, settings = {}},
                            decorative = {treat_missing_as_default = false, settings = {}}},
      no_enemies_mode = true,
      peaceful_mode = true,
    }
    surface = game.create_surface(SURFACE, mgs)
  end
  if CFG.planet and game.planets and game.planets[CFG.planet] then
    local props = game.planets[CFG.planet].prototype.surface_properties or {}
    for name, value in pairs(props) do
      pcall(function() surface.set_property(name, value) end)
    end
  end
  surface.always_day = true
  local half = CFG.half_extent or 64
  local cx, cy = CFG.origin[1], CFG.origin[2]
  surface.request_to_generate_chunks({cx, cy}, math.ceil(half / 32) + 1)
  surface.force_generate_chunk_requests()
  local area = {{cx - half, cy - half}, {cx + half, cy + half}}
  for _, e in pairs(surface.find_entities_filtered{area = area}) do
    if e.valid and e.type ~= "character" then e.destroy() end
  end
  local tiles = {}
  for x = cx - half, cx + half - 1 do
    for y = cy - half, cy + half - 1 do
      tiles[#tiles + 1] = {name = CFG.tile or "lab-dark-1", position = {x, y}}
    end
  end
  surface.set_tiles(tiles, true, false, false, false)
  return surface, area
end

local function prepare_force()
  local force = game.forces[CFG.force or "player"]
  if CFG.research == "all" then
    force.research_all_technologies()
  end
  for name, level in pairs(CFG.tech_levels or {}) do
    local t = force.technologies[name]
    if not t then
      problem("unknown technology " .. name)
    else
      for _, pre in pairs(t.prerequisites) do pre.researched = true end
      local proto = t.prototype
      if proto.max_level ~= proto.level then
        -- multi-level technology: `level` = number of researched levels counted from
        -- this prototype's first level; the engine treats levels below t.level as done.
        t.researched = false
        t.level = proto.level + level
      else
        t.researched = level > 0
      end
    end
  end
  force.reset_technology_effects()
  return force
end

-- ---------------------------------------------------------------- build
local function apply_insert_plan(target, plan)
  local ok, err = pcall(function()
    for _, p in pairs(plan) do
      local id = p.id
      for _, pos in pairs((p.items and p.items.in_inventory) or {}) do
        local inv = target.get_inventory(pos.inventory)
        if inv then
          inv[pos.stack + 1].set_stack{name = id.name, quality = id.quality or "normal", count = pos.count or 1}
        end
      end
    end
  end)
  if not ok then problem("insert plan on " .. target.name .. ": " .. tostring(err)) end
end

local function find_offset(bp_entities, ghosts)
  -- build_blueprint shifts the blueprint; recover the shift from a rarely used entity name
  local by_name, counts = {}, {}
  for _, be in pairs(bp_entities) do
    counts[be.name] = (counts[be.name] or 0) + 1
    by_name[be.name] = by_name[be.name] or {}
    table.insert(by_name[be.name], be.position)
  end
  local world = {}
  for _, g in pairs(ghosts) do
    if g.valid and g.type == "entity-ghost" then
      world[g.ghost_name .. "|" .. g.position.x .. "|" .. g.position.y] = true
    end
  end
  local best_name, best_count = nil, math.huge
  for n, c in pairs(counts) do if c < best_count then best_name, best_count = n, c end end
  if not best_name then return {0, 0} end
  for _, g in pairs(ghosts) do
    if g.valid and g.type == "entity-ghost" and g.ghost_name == best_name then
      for _, bpos in pairs(by_name[best_name]) do
        local ox, oy = g.position.x - bpos.x, g.position.y - bpos.y
        local hits, tries = 0, 0
        for _, be in pairs(bp_entities) do
          tries = tries + 1
          if world[be.name .. "|" .. (be.position.x + ox) .. "|" .. (be.position.y + oy)] then hits = hits + 1 end
          if tries >= 50 then break end
        end
        if hits >= math.min(tries, 50) * 0.9 then return {ox, oy} end
      end
    end
  end
  problem("could not determine blueprint offset; infinity settings were not re-applied")
  return nil
end

local function apply_infinity(surface, bp_entities, offset)
  if not offset then return 0 end
  local n = 0
  for _, be in pairs(bp_entities) do
    local s = be.infinity_settings
    if s then
      local pos = {be.position.x + offset[1], be.position.y + offset[2]}
      local e = surface.find_entity(be.name, pos)
      if not e then
        problem("infinity entity " .. be.name .. " not found at " .. serpent.line(pos))
      else
        local ok, err = pcall(function()
          if e.type == "infinity-container" then
            e.remove_unfiltered_items = s.remove_unfiltered_items or false
            for _, f in pairs(s.filters or {}) do
              e.set_infinity_container_filter(f.index, {name = f.name, quality = f.quality or "normal", count = f.count or 0, mode = f.mode or "at-least", index = f.index})
            end
          elseif e.type == "infinity-pipe" then
            if s.name then
              e.set_infinity_pipe_filter{name = s.name, percentage = s.percentage or 1, temperature = s.temperature, mode = s.mode or "at-least"}
            end
          end
        end)
        if ok then n = n + 1 else problem("infinity settings on " .. be.name .. ": " .. tostring(err)) end
      end
    end
  end
  return n
end

local function build(surface, force)
  local inv = game.create_inventory(1)
  inv.insert{name = "blueprint"}
  local stack = inv[1]
  local result = stack.import_stack(CFG.blueprint)
  if result ~= 0 then problem("import_stack returned " .. tostring(result)) end
  if not stack.is_blueprint_setup() then
    problem("blueprint is empty after import")
    return
  end
  local bp_entities = stack.get_blueprint_entities() or {}
  local ghosts = stack.build_blueprint{surface = surface, force = force, position = CFG.origin,
    build_mode = defines.build_mode.forced, skip_fog_of_war = true, raise_built = false}
  -- mods that swap entities on build (e.g. quality variants) see the revive event when raise_events is on
  local offset = find_offset(bp_entities, ghosts)
  local built, failed = 0, 0
  for _, g in pairs(ghosts) do
    if g.valid and g.type == "entity-ghost" then
      local plan = g.insert_plan
      local gname, gpos, gtype = g.ghost_name, g.position, g.ghost_type
      local _, ent, proxy = g.revive{raise_revive = CFG.raise_events ~= false}
      if proxy and proxy.valid then
        local p2 = proxy.insert_plan
        if p2 and #p2 > 0 then plan = p2 end
        proxy.destroy()
      end
      if not (ent and ent.valid) and CFG.raise_events ~= false then
        -- a mod replaced the entity in its build handler: use the replacement
        local found = surface.find_entities_filtered{position = gpos, type = gtype, force = force, limit = 1}
        ent = found[1]
      end
      if ent and ent.valid then
        built = built + 1
        -- modules: drop whatever a mod may have spilled and insert the planned ones
        for _, pr in pairs(surface.find_entities_filtered{position = gpos, type = "item-request-proxy"}) do pr.destroy() end
        if plan and #plan > 0 then apply_insert_plan(ent, plan) end
      else
        failed = failed + 1
        problem("could not build " .. g.ghost_name .. " at " .. serpent.line(g.position))
      end
    end
  end
  local infinity = apply_infinity(surface, bp_entities, offset)
  state.report.build = {expected_entities = #bp_entities, built = built, failed = failed,
    offset = offset, infinity_entities_configured = infinity}
  inv.destroy()
  if built < #bp_entities then
    problem(string.format("only %d of %d blueprint entities were built (blocked or unsupported)", built, #bp_entities))
  end
end

local function power(surface, force, area)
  local poles = surface.find_entities_filtered{area = area, type = "electric-pole", force = force}
  if #poles == 0 and CFG.auto_power ~= false then
    -- grid of substations wherever there is room
    for x = area[1][1] + 8, area[2][1] - 8, 16 do
      for y = area[1][2] + 8, area[2][2] - 8, 16 do
        local p = surface.find_non_colliding_position("substation", {x, y}, 6, 1, true)
        if p then surface.create_entity{name = "substation", position = p, force = force} end
      end
    end
    poles = surface.find_entities_filtered{area = area, type = "electric-pole", force = force}
    if #poles > 0 then problem("blueprint has no electric poles - testbench placed substations automatically") end
  end
  if #poles == 0 then
    problem("no electric poles: nothing is powered")
    return
  end
  local networks = {}
  for _, pole in pairs(poles) do
    local id = pole.electric_network_id
    if id and not networks[id] then
      networks[id] = pole
    end
  end
  local n = 0
  for _, pole in pairs(networks) do
    local p = surface.find_non_colliding_position("electric-energy-interface", pole.position, 6, 0.5, true)
    if p then
      local eei = surface.create_entity{name = "electric-energy-interface", position = p, force = force}
      eei.electric_buffer_size = 1e15
      eei.power_production = 1e13
      eei.power_usage = 0
      n = n + 1
    end
  end
  state.report.build.electric_networks = n
  if n > 1 then problem(string.format("blueprint has %d separate electric networks (each got its own power source)", n)) end
end

local function robots(surface, force, area)
  local count = CFG.robots_per_roboport or 0
  if count <= 0 then return end
  for _, rp in pairs(surface.find_entities_filtered{area = area, type = "roboport", force = force}) do
    rp.insert{name = CFG.robot_name or "logistic-robot", count = count}
    if (CFG.construction_robots_per_roboport or 0) > 0 then
      rp.insert{name = "construction-robot", count = CFG.construction_robots_per_roboport}
    end
  end
end

local function index_crafters(surface, force, area)
  for _, e in pairs(surface.find_entities_filtered{area = area, type = CRAFTER_TYPES, force = force}) do
    local r, q = nil, nil
    if e.type == "assembling-machine" or e.type == "furnace" or e.type == "rocket-silo" then
      local ok, rr, qq = pcall(function() return e.get_recipe() end)
      if ok and rr then r, q = rr.name, qq and qq.name end
    end
    state.crafters[e.unit_number] = {entity = e, name = e.name, position = {e.position.x, e.position.y},
      recipe = r, recipe_quality = q, counts = {}, samples = 0}
  end
end

-- ---------------------------------------------------------------- sampling
local function production_snapshot(force, surface)
  local stats = force.get_item_production_statistics(surface)
  local out = {}
  for name, _ in pairs(stats.input_counts) do
    for _, q in ipairs(QUALITIES) do
      local v = stats.get_input_count({name = name, quality = q})
      if v and v > 0 then out[name .. "@" .. q] = v end
    end
  end
  local cons = {}
  for name, _ in pairs(stats.output_counts) do
    for _, q in ipairs(QUALITIES) do
      local v = stats.get_output_count({name = name, quality = q})
      if v and v > 0 then cons[name .. "@" .. q] = v end
    end
  end
  local fstats = force.get_fluid_production_statistics(surface)
  local fl = {}
  for name, v in pairs(fstats.input_counts) do fl[name] = v end
  return out, cons, fl
end

local function sample(surface, force, area, final)
  local s = {tick = game.tick - state.start_tick}
  -- crafter states
  local status = {}
  for id, c in pairs(state.crafters) do
    local e = c.entity
    if e.valid then
      local sn = status_name[e.status] or tostring(e.status)
      c.counts[sn] = (c.counts[sn] or 0) + 1
      c.samples = c.samples + 1
      local key = e.name .. "|" .. (c.recipe or "-") .. "|" .. (c.recipe_quality or "")
      status[key] = status[key] or {}
      status[key][sn] = (status[key][sn] or 0) + 1
    end
  end
  s.status = status
  -- containers
  local stock, full = {}, {}
  for _, e in pairs(surface.find_entities_filtered{area = area, type = CONTAINER_TYPES, force = force}) do
    local inv = e.get_inventory(defines.inventory.chest)
    if inv then
      for _, c in pairs(inv.get_contents()) do
        local k = c.name .. "@" .. c.quality
        stock[k] = (stock[k] or 0) + c.count
      end
      local slots = #inv
      local used = slots - inv.count_empty_stacks()
      local fed_by_infinity = surface.count_entities_filtered{position = e.position, radius = 2.6, type = "infinity-container"} > 0
      if slots > 0 and used / slots >= 0.9 and not fed_by_infinity then
        full[#full + 1] = {name = e.name, position = {e.position.x, e.position.y}, used = used, slots = slots}
      end
    end
  end
  s.stock = stock
  s.full_containers = full
  s.produced, s.consumed, s.fluids_produced = production_snapshot(force, surface)
  s.items_on_ground = surface.count_entities_filtered{area = area, type = "item-entity"}
  local unpowered = {}
  for _, e in pairs(surface.find_entities_filtered{area = area, force = force, type = {"inserter", "assembling-machine", "furnace", "roboport", "lab", "mining-drill", "beacon", "pump"}}) do
    local st = e.status
    if st == defines.entity_status.no_power or st == defines.entity_status.low_power then
      local u = unpowered[e.name] or {count = 0, positions = {}}
      u.count = u.count + 1
      if #u.positions < 5 then u.positions[#u.positions + 1] = {e.position.x, e.position.y} end
      unpowered[e.name] = u
    end
  end
  s.unpowered = unpowered
  local nets = {}
  for _, net in pairs((force.logistic_networks or {})[surface.name] or {}) do
    nets[#nets + 1] = {robots = net.all_logistic_robots, available = net.available_logistic_robots,
      storage_free = (function() local f = 0 for _, st in pairs(net.storages) do local i = st.get_inventory(defines.inventory.chest) if i then f = f + i.count_empty_stacks() end end return f end)()}
  end
  s.logistic_networks = nets
  local samples = state.report.samples
  samples[#samples + 1] = s
  if final then
    local per = {}
    for id, c in pairs(state.crafters) do
      per[#per + 1] = {name = c.name, position = c.position, recipe = c.recipe, recipe_quality = c.recipe_quality,
        samples = c.samples, counts = c.counts}
    end
    state.report.crafters = per
  end
end

-- ---------------------------------------------------------------- main loop
local surface_ref, force_ref, area_ref

script.on_event(defines.events.on_tick, function(event)
  if state.phase == "init" then
    local ok, err = pcall(function()
      local surface, area = prepare_surface()
      local force = prepare_force()
      build(surface, force)
      power(surface, force, area)
      robots(surface, force, area)
      index_crafters(surface, force, area)
      surface_ref, force_ref, area_ref = surface, force, area
    end)
    if not ok then
      problem("setup failed: " .. tostring(err))
      state.phase = "done"
      state.report.finished = false
      write_report()
      log("[fbs] DONE")
      error("fbs testbench setup failed - aborting run")
    end
    state.start_tick = game.tick
    state.phase = "run"
    sample(surface_ref, force_ref, area_ref, false)
    write_report()
    return
  end
  if state.phase ~= "run" then return end
  local t = game.tick - state.start_tick
  if t % (CFG.sample_interval or 3600) == 0 then
    local final = t >= CFG.ticks
    local ok, err = pcall(sample, surface_ref, force_ref, area_ref, final)
    if not ok then problem("sampling failed: " .. tostring(err)) end
    if final then
      state.phase = "done"
      state.report.finished = true
      log("[fbs] DONE")
    end
    write_report()
  end
end)
