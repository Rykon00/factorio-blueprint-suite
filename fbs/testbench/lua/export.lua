-- fbs export: turn an area of a save into a blueprint string.
-- The Python side prepends `local FBS_CONFIG_JSON = [==[...]==]`.
local CFG = helpers.json_to_table(FBS_CONFIG_JSON)

local function run()
  local out = {surfaces = {}}
  for _, s in pairs(game.surfaces) do
    out.surfaces[#out.surfaces + 1] = {name = s.name, entities = s.count_entities_filtered{}}
  end
  local surface = CFG.surface and game.surfaces[CFG.surface]
  if not surface then
    out.error = "surface not found: " .. tostring(CFG.surface)
    return out
  end
  local area = CFG.area
  local force = CFG.force and game.forces[CFG.force]
  local ents = surface.find_entities_filtered{area = area}
  if not force then
    local counts = {}
    for _, e in pairs(ents) do
      local f = e.force.name
      if f ~= "neutral" and f ~= "enemy" then counts[f] = (counts[f] or 0) + 1 end
    end
    local best, n = nil, -1
    for f, c in pairs(counts) do if c > n then best, n = f, c end end
    force = best and game.forces[best]
  end
  if not force then
    out.error = "no buildable entities found"
    return out
  end
  if not area then
    local minx, miny, maxx, maxy = math.huge, math.huge, -math.huge, -math.huge
    for _, e in pairs(ents) do
      if e.force == force then
        local b = e.bounding_box
        minx = math.min(minx, b.left_top.x) miny = math.min(miny, b.left_top.y)
        maxx = math.max(maxx, b.right_bottom.x) maxy = math.max(maxy, b.right_bottom.y)
      end
    end
    area = {{minx - 1, miny - 1}, {maxx + 1, maxy + 1}}
  end
  local inv = game.create_inventory(1)
  inv.insert{name = "blueprint"}
  inv[1].create_blueprint{surface = surface, force = force, area = area, include_trains = false, include_station_names = true}
  out.blueprint = inv[1].export_stack()
  out.force = force.name
  out.area = area
  inv.destroy()
  return out
end

local done = false
script.on_event(defines.events.on_tick, function()
  if done then return end
  done = true
  local ok, res = pcall(run)
  if not ok then res = {error = tostring(res)} end
  helpers.write_file("fbs-export.json", helpers.table_to_json(res), false)
end)
