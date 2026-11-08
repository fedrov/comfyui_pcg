# Group patterns

Most geometry nodes have a **Group** field that limits the operation to some of the input's elements, like the Group parameter on a Houdini SOP. The field takes a short pattern: group names, element numbers and ranges, exclusions, or a single `@attribute` expression. This page describes that pattern language, the separate edge-group fields, and the set-algebra syntax of the Group Combine node. Every rule here comes from `geo/groups.py` and `geo/groupcombine.py`.

## The two modes

A pattern is read in one of two ways, decided by a single rule:

- If the text contains `@` anywhere, the **whole field** is one attribute expression.
- Otherwise it is a list of **tokens** separated by spaces.

The two modes cannot be mixed. `@P.y > 0 top` is an error, not "points above zero plus group `top`". To combine a named group with an expression, use two nodes (for example Group Create with the expression, then Group Combine), or express the group as an attribute.

An empty field (or one made only of spaces) means **all elements**. A few secondary fields treat empty as "nothing" instead, for example the start/end point fields of [Find Shortest Path (PCG)](../reference/topology.md#pcg-findshortestpath) and the Constrained Points field of [Smooth (PCG)](../reference/modify.md#pcg-smooth); their reference entry says so.

## Token mode

| Token | Meaning |
|---|---|
| `*` | All elements. |
| `name` | The elements of the named group. |
| `12` | Element number 12. |
| `-1` | Negative numbers count from the end (`-1` is the last element). |
| `0-20` | Elements 0 to 20, both ends included. |
| `0-20:3` | Every third element from 0 to 20 (0, 3, 6, ...). |
| `20-0` | A reversed range is swapped, so this is the same as `0-20`. |
| `!token` | Exclude what `token` selects. |
| `^token` | Same as `!token`. |

Tokens are combined like this:

1. Every token without `!` / `^` is added to an include set (union).
2. Every token with `!` / `^` is added to an exclude set.
3. The result is include minus exclude.
4. If there is **no** include token at all, the include set is everything.

Examples (point groups `a` and `b` on a 16-point grid):

```text
a               the points in group a
a b             points in a or in b
a !b            points in a that are not in b
!a              every point except those in a
0 3 5           points 0, 3 and 5
0-15:3          points 0, 3, 6, 9, 12, 15
* !0-3          everything except the first four points
```

Details worth knowing:

- Range bounds outside the element count are clipped silently (`0-1000` on 16 points selects all 16). A single number outside the range selects nothing.
- An unknown group name is an **error**, and the message lists the groups that do exist on that element class.
- Wildcards in group names (`piece*`) are **not** supported in Group fields. Only the lone `*` is special. Use [Group Combine (PCG)](../reference/group.md#pcg-groupcombine) when you need name wildcards.
- Names are looked up on the element class the node is working on. A point-group name typed into a field that resolves primitives is an error, unless the node converts (see [Group type](#group-type-and-guessing)).

## Expression mode

When the pattern contains `@`, it is evaluated once, vectorised, with the same `@attribute` syntax and function library as the [Wrangle language](wrangle.md). The result must be one true/false value per element.

```text
@P.y > 0.5
@Cd.x > 0.5 & @P.y < 0
@P.x > 0 && @P.z < 0
(@P.x > 0) | (@P.z > 0)
~(@P.x > 0)
@ptnum % 2 == 0
@ptnum >= @numpt - 2
@name == "piece1"
length(@P) < 5
noise(@P * 2) > 0.5
```

Rules:

- `@name` reads an attribute of the element class being resolved; `@P.x` / `.y` / `.z` / `.w` read one component. Reading an attribute that does not exist is an error.
- `@ptnum`, `@primnum`, `@vtxnum`, `@elemnum` all mean "the element number"; `@numpt`, `@numprim`, `@numvtx`, `@numelem` all mean "the element count", whatever the class.
- On primitives, `@P` is the primitive centre (as in VEX), even though primitives have no `P` attribute.
- Combine conditions with `&` (and), `|` (or) and `~` (not). `&&`, `||` and `!` are accepted as aliases, and so are the words `and`, `or` and `not`. The parser adds parentheses around each side of a top-level and / or (also inside brackets), and `not X` / `!X` becomes `~(X)`, so `@P.x > 0 and not @P.z < 0` works without the extra brackets that plain Python/numpy would need. Text inside quotes is left alone (`@name == "a and b"`), and attribute names such as `@band` or `@order` are not split.
- The expression must be a single expression, not statements (no `=` assignment, no `;`).
- A constant result (`1 == 1`) selects all or nothing.
- The field is read-only: it cannot create or change attributes.
- `rand()`, `ch()` and the other Wrangle-node extras that depend on the node's seed or panel are **not** available here. For a random subset use Group Create's *Keep by Random Chance*, or write a random attribute with a Wrangle first and compare it here.

String attributes compare with `==` and `!=` (`@name == "piece1"`).

## Group type and guessing

A pattern is always resolved against one element class: points, primitives or vertices. Which one is decided by the node, usually by a **Group Type** menu next to the field (see the node's reference entry).

Some nodes, notably [Transform (PCG)](../reference/modify.md#pcg-transform), use Houdini's *guess* behaviour: the pattern is first resolved as points; if that fails because the name or attribute exists only on primitives, it is resolved as primitives and the points used by those primitives are taken. So a primitive group name or a primitive-attribute test such as `@part == "LOD1"` works in Transform's Group field.

When a node converts between classes internally, the plugin uses these rules:

- primitive selection to points: every point used by a selected primitive;
- point selection to primitives: a primitive counts only if **all** its points are selected.

## Edge groups

Edges are not an element class of their own; an edge group is stored as a list of point pairs, so it survives operations that renumber edges. Fields that take edges (for example seam, crease or cut-edge fields, and Group Type *Edges* where a node offers it) accept a simpler syntax:

| Pattern | Meaning |
|---|---|
| empty or `*` | Every edge of the current geometry. |
| `seams` | The edges in edge group `seams`. |
| `seams hard` | Union of several edge groups. |
| `seam_*` | Wildcards (`*`, `?`, `[...]`): every edge group whose name matches. A wildcard that matches nothing selects nothing. |
| `p3-7` | Houdini's point-pair syntax: the edge between points 3 and 7. `p0-1-2` is the chain 0-1, 1-2. |

There are no numbers, ranges, exclusions or expressions for edges, because edge numbers change whenever topology changes. An **unknown edge-group name is an error** (the message lists the edge groups that exist), the same as for point and primitive groups. In earlier versions unknown names were ignored silently, so a misspelt name made the edge operation do nothing.

To select edges by angle, boundary, length or random chance, build an edge group with [Group Create (PCG)](../reference/group.md#pcg-groupcreate) or [Group Edges (PCG)](../reference/group.md#pcg-groupedges). To convert between edge and point / primitive groups, use [Group Promote (PCG)](../reference/group.md#pcg-grouppromote) or [Edge Group Promote (PCG)](../reference/group.md#pcg-edgegrouppromote).

## Group Combine expressions

[Group Combine (PCG)](../reference/group.md#pcg-groupcombine) builds a new group from existing ones with set algebra. Its expression is **not** a Group-field pattern; it has its own syntax:

| Operator | Meaning | Precedence |
|---|---|---|
| `!a`, `~a` | Complement (everything not in `a`) | highest |
| `a - b` | Difference | |
| `a & b` | Intersection | |
| `a ^ b` | Symmetric difference (in exactly one) | |
| `a \| b` | Union | lowest |

Parentheses nest freely. Group names may contain the wildcards `*`, `?` and `[...]`; a wildcard name stands for the union of all matching groups, and `*` alone is the whole set. A name that matches no group is an error. Group Type selects point, primitive, vertex or edge groups; for edges the universe is every edge of the current topology.

```text
(top & selected) - border
!(a | b)
piece* ^ keep
```

Note that `^` means "exclude" in a Group field but "symmetric difference" in Group Combine.

## Filling the field from upstream

Group and attribute name fields have a small `▾` button in the panel, and the node's right-click menu has a fill entry. Both list the groups (and attributes) that actually exist on the **upstream** geometry, collected the last time the upstream nodes ran. If the list is empty, run the graph once. In the right-click menu, the second half of each list appends the name to the field instead of replacing it.

## See also

- [Geometry](geometry.md): element classes and how groups are stored.
- [Expressions](expressions.md): the full `@attribute` syntax and function list.
- Group nodes: [Group Create](../reference/group.md#pcg-groupcreate), [Group Combine](../reference/group.md#pcg-groupcombine), [Group Expand](../reference/group.md#pcg-groupexpand), [Group Promote](../reference/group.md#pcg-grouppromote), [Group Delete](../reference/group.md#pcg-groupdelete), [Blast](../reference/modify.md#pcg-blast) and the rest of the [Groups reference](../reference/group.md).
