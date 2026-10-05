"""Recipe graph handling and inventory accounting for the crafting bench."""

from collections import defaultdict

MAX_DEPTH = 24


class CraftingError(Exception):
    """Raised when a recipe is malformed or a crafting request cannot be met."""


class Recipe:
    """One crafting recipe."""

    def __init__(self, rid, name, inputs, outputs, byproducts=None, tool=None,
                 tool_uses=0, workbench=0, priority=0):
        self.rid = rid
        self.name = name
        self.inputs = dict(inputs)
        self.outputs = dict(outputs)
        self.byproducts = dict(byproducts or {})
        self.tool = tool
        self.tool_uses = tool_uses
        self.workbench = workbench
        self.priority = priority

    def __repr__(self):
        return "Recipe(%r, %r)" % (self.rid, self.name)


def parse_recipe(raw):
    """Build a Recipe from a raw mapping, raising CraftingError when malformed."""
    rid = raw.get("id")
    name = raw.get("name")
    if not rid or not name:
        raise CraftingError("a recipe needs an id and a name")
    inputs = raw.get("inputs") or {}
    outputs = raw.get("outputs") or {}
    byproducts = raw.get("byproducts") or {}
    tables = (inputs, outputs, byproducts)
    for table in tables:
        if not isinstance(table, dict):
            raise CraftingError("recipe %s has a malformed table" % rid)
    if not inputs:
        raise CraftingError("recipe %s has no inputs" % rid)
    if not outputs:
        raise CraftingError("recipe %s has no outputs" % rid)
    if name not in outputs:
        raise CraftingError("recipe %s does not yield %s" % (rid, name))
    for table in tables:
        for item, qty in table.items():
            if not isinstance(qty, int) or qty < 0:
                raise CraftingError("recipe %s has a bad amount of %s" % (rid, item))
    workbench = raw.get("workbench", 0)
    priority = raw.get("priority", 0)
    tool = raw.get("tool")
    tool_uses = raw.get("tool_uses", 0)
    if not isinstance(workbench, int) or workbench < 0:
        raise CraftingError("recipe %s has a bad workbench level" % rid)
    if not isinstance(priority, int):
        raise CraftingError("recipe %s has a bad priority" % rid)
    if not isinstance(tool_uses, int) or tool_uses < 0:
        raise CraftingError("recipe %s has a bad tool_uses" % rid)
    if tool is None and tool_uses:
        raise CraftingError("recipe %s charges tool uses without a tool" % rid)
    return Recipe(rid, name, inputs, outputs, byproducts, tool, tool_uses,
                  workbench, priority)


def build_index(recipes):
    """Group recipes by the product they make, first entry ready to use."""
    index = defaultdict(list)
    for recipe in recipes:
        index[recipe.name].append(recipe)
    for entries in index.values():
        entries.sort(key=lambda recipe: recipe.priority)
    return dict(index)


def pick_recipe(index, product, workbench=0):
    """Return the recipe to run for product at the given workbench level."""
    usable = [entry for entry in index.get(product, ()) if entry.workbench >= workbench]
    if not usable:
        raise CraftingError("no recipe for %s at workbench %d" % (product, workbench))
    return usable[0]


def find_cycles(index):
    """Return the products that take part in a dependency cycle, sorted by name."""
    found = []
    for product in sorted(index):
        for recipe in index[product]:
            if product in recipe.inputs:
                found.append(product)
                break
    return found


def craft(inventory, index, product, count, workbench=0):
    """Run the recipe for product until count units have been produced.

    A new inventory mapping is returned; the argument is left untouched.
    """
    if count <= 0:
        raise CraftingError("count must be positive")
    recipe = pick_recipe(index, product, workbench)
    batches = _batch_count(recipe, product, count)
    result = dict(inventory)
    for item, need in recipe.inputs.items():
        _take(result, item, need * batches)
    if recipe.tool and recipe.tool in result:
        _take(result, recipe.tool, recipe.tool_uses * batches)
    for item, qty in _gains(recipe, batches).items():
        result[item] = result.get(item, 0) + qty
    return result


def can_craft(inventory, index, product, count, workbench=0):
    """Return True when count units of product can be produced from the inventory."""
    if count <= 0:
        raise CraftingError("count must be positive")
    recipe = _select(index, product, workbench)
    if recipe is None:
        return False
    batches = _batch_count(recipe, product, count)
    for item, need in recipe.inputs.items():
        short = need * batches - inventory.get(item, 0)
        if short <= 0:
            continue
        if not _coverable(inventory, index, item, short, workbench):
            return False
    if recipe.tool and inventory.get(recipe.tool, 0) < recipe.tool_uses * batches:
        return False
    return True


def total_stock(inventory, index, product, workbench=0):
    """Return how many units of product the inventory can yield in total."""
    on_hand = inventory.get(product, 0)
    recipe = _select(index, product, workbench)
    if recipe is None:
        return on_hand
    runs = _runs_on_hand(inventory, recipe, product)
    return on_hand + runs * recipe.outputs.get(product, 0)


def _select(index, product, workbench):
    """Return the recipe to run, or None when the index has nothing usable."""
    try:
        return pick_recipe(index, product, workbench)
    except CraftingError:
        return None


def _batch_count(recipe, product, count):
    """Return how many runs of recipe are needed to obtain count units of product."""
    per_run = recipe.outputs.get(product, 0)
    if per_run <= 0:
        raise CraftingError("recipe %s does not yield %s" % (recipe.rid, product))
    return count // per_run


def _gains(recipe, batches):
    """Return the items a run of batches turns out."""
    gains = {}
    for item, qty in recipe.outputs.items():
        gains[item] = gains.get(item, 0) + qty * batches
    return gains


def _take(inventory, item, qty):
    """Remove qty of item from inventory, refusing to go below zero."""
    have = inventory.get(item, 0)
    if have < qty:
        raise CraftingError("not enough %s: need %d, have %d" % (item, qty, have))
    inventory[item] = have - qty


def _runs_on_hand(inventory, recipe, product):
    """Return how many runs of recipe the items on hand allow."""
    limits = []
    for item, need in recipe.inputs.items():
        limits.append(inventory.get(item, 0) // need)
    if not limits:
        return 0
    return min(limits)


def _coverable(inventory, index, item, shortfall, workbench=0, depth=0):
    """Return True when shortfall more units of item can be assembled right now."""
    if depth > MAX_DEPTH:
        raise CraftingError("recipe graph too deep at %s" % item)
    recipe = _select(index, item, workbench)
    if recipe is None:
        return False
    batches = _batch_count(recipe, item, shortfall)
    for part, need in recipe.inputs.items():
        short = need * batches - inventory.get(part, 0)
        if short <= 0:
            continue
        if not _coverable(inventory, index, part, short, workbench, depth + 1):
            return False
    return True
