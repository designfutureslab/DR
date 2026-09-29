title: DR1 Drawing Robot

<!--
  DETAILED WALKTHROUGH: deep dives into the clusters.
  The big-picture story lives in brief.md; this file goes one level down.
  Each "## Title" is a step; @doc picks the canvas (cluster path from the main
  canvas, e.g. "DR robotic Motions/DFL weaver"); @focus frames the view.
  A list where every item starts with [Name] becomes numbered pins.
-->

# Inside the clusters

## Drawing Setup: finding the paper
@doc: DR Drawing Setup

This cluster works out exactly where the paper is, then makes the two working planes above and below it. It receives the Drawing Data (for pressure and retract heights), the paper size and the fixture position.

- [4 point Calibration] The paper plane measured on the robot. Each corner of the paper was touched with the pen tip; the four X, Y, Z points are fitted into a plane. A **Stream Filter** picks Charlie's points, Darcy's points or your own custom points, depending on the *4 pt plane In use* list.
- [Paper Size and position] The *ideal* paper plane: centred on the fixture, using its X distance from the robot and its height. Used when calibration is switched off.
- [Paper Plane] Chooses between the ideal and the calibrated plane (the *Use 4 pt Calibrated plane* toggle).
- [Create Transfer Planes] The paper plane raised by each tool's retract height: where the pen travels between strokes.
- [Create Pressure planes] The paper plane lowered by each tool's pressure: where the pen draws.

The two **Py3** scripts on the left download the latest calibration files from the lab's GitHub repository when you click *Get Latest Calibration Data*. They also report when each file was last updated.

?? The fetched Darcy points feed the calibration filter, but the Charlie points seem to come from a fixed panel ("4 Point Charlie"), not from the download. Is that intended, or should Charlie's download be wired in too?

## Path Planning: curves to planes
@doc: DR Path Planning

The heart of the geometry. Curves go in; one oriented plane per pen-tip position comes out.

- [Contour Curves] Picks slot 3 (the curves) out of every tool's Drawing Data.
- [Move Drawing To Paper] Projects the curves flat onto the paper plane and moves them so the drawing is centred on the paper.
- [DFL Curves to Planes] Converts each curve to a polyline within the tolerance, then puts a plane at every vertex.
- [Reorient Planes] Works out how to turn the planes so the pen points down into the paper: 180° about X, then 90° about Z.
- [Orient] Applies that turn to every plane in one step.

The two *re-orient* clusters only ever rotate **one** plane, World XY. Rotating each path plane about its own axes gives exactly the same result as rotating World XY and then orienting it onto that plane. So one **Orient** does the work that used to take about fourteen operations per plane.

The **Pen Tilt** sliders add a small extra rotation. A few degrees of tilt can move the robot's wrist away from a singularity without changing the drawing.

> **Tip:** Want smoother curves? Lower the tolerance slider on the main canvas. Each halving roughly doubles the number of planes, so watch the 40,000 limit.

## Robotic Motions: the choreography
@doc: DR robotic Motions
@focus: Initial Pose, Pen Change, Lead In, Lead Out, Linear Movements

This cluster turns planes into the robot's full sequence of moves. Read it top to bottom:

- [Initial Pose] A safety pop-up for the operator, then a joint move to a known safe pose.
- [Pen Change] For each tool, a move to the tool-change pose and a pop-up: "Insert *tool name* layer and click continue to resume". The robot waits there.
- [Lead In] The first plane of every stroke, lifted to the transfer height: the robot arrives above the start of each line. The small **Py3** script pairs the right tool with every stroke.
- [Linear Movements] The drawing itself: linear moves through every plane at the drawing speed and zone.
- [Lead Out] The last plane of each stroke, lifted again, so the pen leaves the paper cleanly.
- [Order Program] Merges start, drawing and finish into one ordered list of targets.

**Insert Items** components splice the lead-in onto the front of each stroke and the lead-out onto the end, so every stroke is: *above start → down → draw → up*.

## Robotic Motions: painting and the brush
@doc: DR robotic Motions
@focus: Locate Paint pot at Pen Orientation, Set Safe Height, Set Dip + Wipe, Paint pot refill motions, GTP5 Py3 Insert Strokes

The brush needs paint, so painting tools get extra moves.

- [Locate Paint pot at Pen Orientation] Moves a stroke's first plane to the paint pot, so the brush arrives at the pot pointing the same way it paints.
- [Set Safe Height] A point 80 mm above the pot, to approach from.
- [Set Dip + Wipe] Down 10 mm into the paint, then across and up to wipe the brush on the pot's edge.
- [Paint pot refill motions] Turns those planes into robot targets: approach, dip, wipe.
- [GTP5 Py3 Insert Strokes] A Python script that inserts the dip sequence before the first stroke of each tool, then again every *N* strokes (*# Strokes Per Refill* on the main canvas).
- [DFL weaver] Picks, for each tool, the drawing motions or the painting motions. It also adds the tool-change moves between tools.

## DFL weaver and More than 1?
@doc: DR robotic Motions/DFL weaver

The weaver decides what each tool's moves look like.

- [GTP5 Py3 SEL Branch] For every tool branch, chooses the *drawing* motions or the *painting* motions using the tool's Motion Type (slot 4 of the Drawing Data).
- [Weave] When more than one tool is used, interleaves the tool-change moves with each tool's strokes: change → draw tool 1 → change → draw tool 2 …
- [Merge] The single-tool path: no tool changes needed after the first.

The small [[DR robotic Motions::More than 1?|More than 1?]] cluster just counts the tools and answers true or false. It drives the Stream Filters here.

## The pen test program
@doc: DR robotic Motions/DFL Tool Test

A second, short program saved alongside your drawing (if *Include Pen Test Script* is on). Run it first to set the pen height.

- [Initial Pose] Safety message and move to a safe pose.
- [Pen Change] Move to the tool-change pose and ask for the pen to be inserted.
- [Order Program] The test sequence: go above the paper, pause for a spacer to be inserted, lower slowly to 20 mm, then pause so the operator can adjust the pen until its tip just rests on the spacer.
- [Create program] Builds the program, named after your project plus `_pentest`.

## The tool builder (DFL DR2 Tool)
@doc: DFL DR2 Tool

Every tool block on the main canvas (Stabilo, pencil, brush, custom) wraps this same cluster. It builds a Robots **tool** and packs the Drawing Data bundle.

- [PenHolder1] and [PenHolder2] Two versions of the DFL pen holder. Each builds a 3D model of holder plus pen from the pen length and diameter, and works out where the tip is. *New pen holder?* chooses which.
- [Create tool] The Robots tool: name, TCP plane (tip position), weight and mesh. If *Use Calibrated TCP* is on, the tip position comes from your calibration numbers instead of the holder model.
- [Entwine] Packs the eight Drawing Data slots in order (see [[step:the-drawing-data-bundle|The Drawing Data bundle]]).

## Fixtures and the work cell
@doc: DFL UR fixtures

Builds everything around the robot for the preview, and reports where the fixture surface is.

- [Fixture X] The fixture's distance from the robot, in mm. The paper is centred here.
- [Fixture Z] The fixture's height, in mm. The paper sits at this height.

Most of this cluster is meshes: the table or cart, the adaptor plate, the fixture track and the fixture models. Pick a fixture from *ALL fixtures* on the main canvas and this cluster moves and shows the matching model.

## Previewing the toolpath
@doc: DR preview

Draws the path the pen tip will follow, coloured by tool, so you can check the drawing before simulating.

- [DeconstructTarget] Takes every robot target back apart to get its plane.
- [PLine] Joins the target positions into polylines: the actual toolpath.
- [Preview Colours] Uses each tool's preview colour (slot 2 of the Drawing Data).
- [Filter] Chooses whether to show the travel moves between strokes (*preview Transitions* on the main canvas).

## Unique file names
@doc: Cluster (2)

A small helper next to the Save button. The robot will not load two programs with the same name, so every save gets a number.

- [Click Log] The Save button's clicks, recorded by the Data Recorder outside (each click records both True and False).
- [Rep] Replaces spaces in the project name with underscores.
- [Concat] Joins the project name, `_` and the click count, for example `demo1_3`.

## Hatching (RB HATCH 2025)
@doc: RB HATCH 2025

Fills closed shapes with lines, so a drawing can have shading. The main canvas exposes the settings: angle, gap, and straight or zig-zag hatching.

- [RB bounding Hatch] Makes parallel lines covering the shape's bounding box at the hatch angle and gap.
- [Trim] Trims the lines to the inside of the shape.
- [#048bbab2|Weave] For zig-zag hatching, alternate lines are flipped and joined end to end, so the pen draws them in one continuous stroke.
