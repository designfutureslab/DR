name: DR1 Drawing Robot
subtitle: How the DFL drawing and painting script works, stage by stage
purpose: Turns 2D curves drawn in Rhino into a program that makes a Universal Robots UR5 draw or paint them on paper, with pen changes, paint-pot dips and safety pauses built in.
audience: BENV2001 students using Grasshopper and the DFL robots for the first time
rename: Entwine=Drawing Data (all tools), LoadRobot=Robot system, Crv=Your drawing curves, Calibration Test Curves=Test curves

<!--
  This is the SCRIPT BRIEF: the big-picture story of the definition.
  - "## Stage: X" sections become the stages on the map. @covers lists the
    groups (by name, or #id for unnamed ones) that make up the stage; the
    arrows between stages are worked out from the real wires by build.py.
  - "## Concept: X" sections explain ideas a newcomer needs.
  - Lines starting "??" are open questions; they show as "To confirm" boxes
    and are listed by build.py until they are answered and removed.
  See README.md for the full format.
-->

# The big picture

## How it all fits together
@view: map

The script is a production line. Curves you draw in Rhino go in at the top; a `.urp` robot program file comes out at the bottom. Along the way each stage adds one kind of information: which **tool** draws each curve, where the **paper** is, the exact **path** the pen tip follows, and the **robot moves** that follow that path.

Read the map from top to bottom. Each box is a coloured area on the Grasshopper canvas (on the canvas itself they run left to right). Each arrow is real data flowing between them, labelled with the name of that data, and the dashed arrows are values that loop back, like the file name. Click any box to open that stage.

Two ideas hold it all together:

- Everything about one tool (its name, its size, its curves, how hard to press) travels together as one bundle called the **Drawing Data**. See [[step:the-drawing-data-bundle|The Drawing Data bundle]].
- The robot never sees your curves. It sees **planes**: thousands of little coordinate systems placed along each curve, telling it where the pen tip goes and which way it points. See [[step:planes-tcp-and-the-paper|Planes, TCP and the paper]].

> **Tip:** You only need to *change* things in stages 2, 4, 5 and 9. The rest runs by itself, but knowing what it does makes the simulation and any errors much easier to understand.

## Stage: Start here
@covers: #3e5354c0

This corner of the canvas is the script's cover page. It holds the instructions panel and the credits, plus a small **Bifocals** component that prints the name above every component on the canvas.

- [Grasshopper Instructions] The short version of the whole workflow: first-time set-up, the student tool calibration exercise and day-to-day use. The rest of this walkthrough expands each line.
- [info] Written by Richard Blackwell and Charlotte Firth for the Design Futures Lab and BENV2001.
- [Bifocals] Shows component names on the canvas, so you can find things mentioned in the instructions.

> **Important:** First time on a new computer? The robot model comes from the **Robots** plug-in's library. Find [[LoadRobot]] in the Robot Setup stage, click **Libraries**, choose the Universal Robots library and click **Install**.

## Stage: Your drawing
@covers: Drawing Examples, RB Drawing Cleanup, RB HATCH 2025, #548bf3ea

Everything starts as curves in Rhino. This stage is where they come in, and where optional helpers make them easier to draw.

- [#548bf3ea|Your drawing curves] The main input. Right-click it, choose *Set Multiple Curves* and select your drawing in Rhino. It is currently wired to the Stabilo pen tool.
- [Drawing Examples] Ready-made curves for testing: a calibration pattern and the DFL logo.
- [RB Drawing Cleanup] Optional tidy-up for messy drawings. It removes curves shorter than a minimum length and shapes smaller than a minimum area, then rebuilds what is left into smooth curves.
- [RB HATCH 2025] Optional shading. It fills closed shapes with parallel lines at a chosen angle and gap, as straight lines or zig-zags, so the robot can "colour in".

?? Your drawing is referenced from the Rhino file, so it only appears when that .3dm is open. Is there a standard Rhino file students should start from?

## Stage: Work cell and fixtures
@covers: #9c3b86b0

The robot needs to know what is around it: whether it sits on the **cart** or a **table**, and which **fixture** holds the paper. The fixture decides where the paper surface is, so it feeds the paper position in the next stages.

- [Robot Placement] Cart or Table.
- [ALL fixtures] The fixture on the work table. For drawing this is almost always *Draw Table*.
- [DFL UR fixtures] Builds 3D models of the table, mounts and fixture for the preview. It also outputs the fixture's X distance and height, which position the paper.
- [Sandbox X gap] Only matters for the sand box fixture.

The paint pots for the brush tool are also placed here (the small cluster at the right of the group), because they sit on the fixture.

## Stage: Tools
@covers: DFL FULL TOOL, DFL IKEA PENCIL, DFL PAINT BRUSH, Make Custom Tool, Student Calibration Test Results

A **tool** is whatever the robot holds: a Stabilo pen, a pencil, a brush or your own. Each tool block takes some curves and produces one **Drawing Data** bundle: the curves plus everything the robot needs to know to draw them with that tool.

- [DFL FULL TOOL] The standard Stabilo pen. Wire curves into `PEN DRAWING`.
- [DFL IKEA PENCIL] A pencil. Pencils wear down, so recalibrate between drawings.
- [DFL PAINT BRUSH] A brush that dips into a paint pot every few strokes.
- [Make Custom Tool] Build your own tool: measure its length and diameter, and set how hard it presses and how high it lifts between strokes.
- [Student Calibration Test Results] Where you type the X, Y, Z tool-tip offset from a calibration session with DFL staff.

The two numbers you will change most often:

- **Pressure** (mm): how far past the paper surface the tool is pushed. The pen holders are sprung, so 1 to 2 mm gives a firm, even line.
- **Retract** (mm): how high the tool lifts when travelling between strokes.

> **Tip:** Each tool block is a cluster. Double-click one in Grasshopper to see how the tool's 3D model and tip position (TCP) are built. [[doc:DFL DR2 Tool|Look inside the tool builder]].

## Stage: Paper and drawing order
@covers: Drawing Layers

This stage answers two questions: **where is the paper**, and **in what order are the tools used**?

- [Paper Length (x)] Paper size in mm. A3 is 297 by 420.
- [Paper Width (y)]
- [Use 4 pt Calibrated plane] When on, the paper position comes from touching its 4 corners with the robot instead of the ideal fixture position. Turn this on for real drawings.
- [4 pt plane In use] Which robot's calibration to use: Charlie, Darcy, or a custom one you measured.
- [Get Latest Calibration Data] Downloads the newest corner measurements for the lab robots from GitHub.
- [Entwine] **The drawing order.** Plug each tool's Drawing Data into this in the order you want them drawn: first input first.
- [Dam] The Data Dam holds everything back until you press its play button, so the heavy calculation does not re-run on every tweak.

?? Are Charlie and Darcy the names of the lab's two robot cells? And should students always pick the one they are booked on?

## Stage: Path planning
@covers: Number of planes (should not exceed 40,000)

Here the curves become **planes** the robot can follow. [[DR Path Planning]] moves your drawing onto the centre of the paper, breaks every curve into short straight segments, and puts a plane at each point, pointing the pen down into the paper.

- [DR Path Planning] The cluster that does the work. [[doc:DR Path Planning|Look inside]].
- [Number of Planes (should not exceed 40,000)] How many points the robot must visit. Very detailed drawings can go over the robot controller's limit.

The slider next to the cluster is the **tolerance** in mm: how far the straight segments may stray from your true curve. Smaller means smoother but more planes.

> **Important:** If the plane count goes over about 40,000, simplify the drawing (use the cleanup tools) or raise the tolerance.

## Stage: Robot moves
@covers: Robot Setup + initial pose

Now the planes become robot **targets**: positions plus how fast to get there and how precisely. [[DR robotic Motions]] assembles the whole performance:

1. A safety pause and a move to a safe starting pose.
2. For each tool: a pause that asks the operator to load it.
3. For each stroke: move above the start, lower onto the paper, draw along the planes, lift off.
4. For the brush: a dip in the paint pot and a wipe every few strokes.
5. A final "Job Complete" message.

- [List] Choose the robot model. The DFL robots are UR5s.
- [LoadRobot] Loads the robot, so every target can be checked against what the arm can reach.
- [Controlled Speed] Drawing speed in mm/s. Slower gives a cleaner line.
- [Transfer Speed] Speed for moves in the air between strokes.
- [Zone Accuracy] How closely (in mm) the robot must pass through each point. A small zone lets the robot blend points into smooth motion without stopping at each one.
- [# Strokes Per Refill] For the brush: how many strokes between paint-pot dips.
- [Pen Change Pose AV Degrees] The six joint angles of the pose where the operator changes tools.

## Stage: Simulate and check
@covers: #9ccc6148

Before anything goes near the robot, check the program here. [[Create program]] turns the targets into a UR program and reports problems. [[Program simulation]] shows the robot moving.

- [Sim slider] Drag to scrub through the program from start (0) to end (1).
- [Any Program Errors] Must be empty before you save. Errors mean the robot cannot reach a point or would hit a limit.
- [Any Program Warnings] Read these too. They often point at awkward wrist positions.
- [Each Axis Rotation Analysis] The six joint angles at the current moment. Watch for joints spinning near their limits.
- [Duration Minutes] How long the drawing will take.
- [preview Transitions] Show or hide the travel moves between strokes in the preview.

> **Tip:** Joints flipping suddenly in the simulation (a "singularity")? Try the *Pen Tilt* slider inside Path Planning. Tilting the pen slightly often fixes it.

## Stage: Save for the robot
@covers: Save URP

The last step writes the program to a USB stick as a `.urp` file the robot's teach pendant can open.

- [Project Name] Your project name, no spaces.
- [Select a Directory] Right-click and choose your USB drive.
- [Save as URP] Saves the file. A counter adds a number to each save, because the robot controller will not load two files with the same name.
- [Include Pen Test Script] Also saves a short *pen test* program for checking pen height before the real drawing.
- [Saving Instructions] The same steps, on the canvas.

> **Important:** If the Save button flashes red, the folder is not set or the USB stick is not mounted.

# Key concepts

## Concept: The Drawing Data bundle
@focus: Collate Drawing Steps

Every tool cluster outputs one **Drawing Data** tree. It is a bundle with eight numbered slots, so the rest of the script can pick out exactly what it needs. When several tools are plugged into [[Entwine]], the first number of each path becomes the tool number: `{0;…}` is the first tool, `{1;…}` the second, and so on.

| Slot | Contains | Used by |
| --- | --- | --- |
| `{tool;0}` | tool name | pen-change pop-up message |
| `{tool;1}` | the Robots *tool* (tip position, weight, 3D model) | every robot target |
| `{tool;2}` | preview colour | the toolpath preview |
| `{tool;3}` | the curves to draw | path planning |
| `{tool;4}` | drawing or painting | chooses stroke-by-stroke or dip-and-paint motions |
| `{tool;5}` | pressure (mm) | the pen-down plane |
| `{tool;6}` | retract height (mm) | the pen-up plane |
| `{tool;7}` | paint pot position | brush dips |

Inside the clusters you will see **Split Tree** components with masks like `{?;3}`. That means "slot 3 of every tool": the curves.

## Concept: Planes, TCP and the paper
@doc: DR Drawing Setup

Robots are told where to go with **planes**: a point plus three directions. For drawing, three planes matter:

- **Paper plane**: the paper surface, found from the fixture or from touching the 4 corners.
- **Pen pressed plane**: the paper plane pushed *down* by the tool's pressure value. Aiming below the surface is what keeps a sprung pen in firm contact.
- **Transfer plane**: the paper plane lifted *up* by the retract height, for travel between strokes.

The **TCP** (tool centre point) is the tip of the pen, measured from the robot's flange. When the robot moves "to a plane", it is this tip that arrives there, so an accurate TCP matters as much as an accurate paper plane. That is why pens are calibrated.

## Concept: Targets, speed and zone
@doc: DR robotic Motions
@focus: Lead In

A **target** is a plane plus instructions: which tool, how to move (*Linear* keeps the tip on a straight line; *Joint* is faster but curves through the air), how fast, and the zone. Every stroke becomes: lead-in above the start, down onto the paper, the drawing planes, and a lead-out lift.

## Concept: Pauses and pop-ups
@doc: DR robotic Motions/DFL UR Custom Popup

The robot program can stop and show a message on the teach pendant: "Insert Stabilo layer and click continue to resume". The **DFL UR Custom Popup** cluster builds that as a line of URScript (`popup("…", title="…", blocking=True)`) and attaches it to a target as a custom command, so the robot pauses exactly there.

# Using it in the lab

## Workflow
@focus: Grasshopper Instructions

1. **First time only:** install the Universal Robots library (see [[step:start-here|Start here]]).
2. **Calibrate your tool** with DFL staff if you are using your own pen: run the 4-point TCP calibration, enter the X, Y, Z result and turn on *Use Calibrated TCP*.
3. **Clear the example data** and set your own curves in *Your drawing curves*.
4. **Choose tools** and wire the curves into them. Set pressure and retract.
5. **Set the drawing order** by plugging tools into *Entwine*, then press the **Data Dam** play button.
6. **Simulate**. Scrub the slider, and fix any errors and warnings. Adjust *Pen Tilt* if the wrist flips.
7. **Name the project**, choose the USB folder and click **Save as URP**.
8. At the robot: **File → Load Program**, select your `.urp`, run the **pen test** first, then the drawing.

?? Is there a booking or sign-off step with DFL staff before running on the robot that should be listed here?

## Gotchas
@focus: Save URP, Number of planes (should not exceed 40,000)

- **Nothing updates?** The Data Dam is holding the old result. Press its play button.
- **Too many planes** (over 40,000): simplify the drawing, use the cleanup tools, or raise the path tolerance.
- **Save button flashes red:** no folder is chosen, or the USB stick is not mounted.
- **"File already exists" on the robot:** every save needs a new name. The click counter does this for you, so don't reset it mid-session.
- **Pencils blunt.** Recalibrate between pencil drawings.
- **Curves missing?** Referenced curves only exist while the matching Rhino file is open.
- **Wrist flips or errors near the paper edge:** try *Pen Tilt*, or move the drawing towards the centre of the paper.
