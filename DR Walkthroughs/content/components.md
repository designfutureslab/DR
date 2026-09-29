<!--
  COMPONENT NOTES: shown in the inspector for EVERY component of that type.
  "## Type name" must match the component's type (as shown in the inspector
  chip, e.g. "Create Target"). Grasshopper's own description is shown anyway,
  so use these notes for what the component means *in this script*.
-->

## Create Target
A **Robots** component. It turns a plane (or six joint angles) into something the robot can move to, with the tool, motion type (*Joint* or *Linear*), speed and zone attached. It can also carry a command to run on arrival, such as a pop-up. Every move in the program is one of these.

## Create target
The older version of **Create Target** from the Robots plug-in. It does the same job.

## Create program
A **Robots** component. It collects every target into a program for the chosen robot, checks each move (reach, joint limits, speed) and writes the UR code. Its *Errors* and *Warnings* outputs are the first place to look when something is wrong.

## Program simulation
A **Robots** component. It plays the program back in the Rhino viewport. *Time* runs from 0 (start) to 1 (end) when *Normalized* is on, which is what the *Sim slider* drives.

## Load robot system
A **Robots** component. It loads the robot model (here a UR5) from the Robots library. If it shows an error on a new computer, install the Universal Robots library from its **Libraries** button.

## Custom command
A **Robots** component. It wraps a line of robot code (URScript) so it can run at a target. Here it carries the `popup(...)` messages that pause the robot for the operator.

## Create tool
A **Robots** component. It describes what the robot is holding: the tool centre point (TCP), its weight and its 3D model. The TCP is where every target plane is reached.

## Save program
A **Robots** component. It writes the finished program to disk as `.urp` (and supporting files) when its folder input receives a path. The Dispatch next to it only passes the folder through when *Save as URP* is pressed.

## Degrees to radians
A **Robots** component. The robot wants joint angles in radians; people think in degrees. This converts the six pose angles typed in the panels.

## Data Dam
Holds data back until you press its play button. It stops the heavy robot calculation from re-running every time you nudge a slider. If nothing changes after an edit, press play.

## Entwine
Combines several inputs into one data tree, giving each input its own branch number. On the main canvas the input order is the **drawing order** of the tools. Inside the tool builder it packs the eight Drawing Data slots.

## Split Tree
Picks branches out of a data tree with a mask like `{?;3}`: "every branch whose second number is 3". Throughout this script it pulls one slot (curves, pressure, tool...) out of the Drawing Data bundle.

## Trim Tree
Removes the last level of branch numbering. After a Split Tree picks `{tool;3}`, trimming leaves one branch per tool, which is easier to use downstream.

## Stream Filter
A switch: the number at *G* chooses which input passes through. It is used for toggles and choices, for example ideal or calibrated paper, old or new pen holder, and drawing or painting.

## Data Recorder
Keeps a history of every value it receives. Here it counts clicks on *Save as URP* so each saved file gets a new number. Clear it with the **X** on the component to reset the count.

## Weave
Interleaves items from several lists in a set pattern (0, 1, 0, 1...). It is used to alternate tool-change moves with drawing, and to join zig-zag hatch lines.

## Insert Items
Inserts items into a list at a given index. Here it adds the lead-in move at the start of each stroke (index 0) and the lead-out at the end (index −1).

## Plane Offset
Moves a plane along its own Z axis. Positive lifts it (transfer planes); negative pushes it below the paper (pressure planes).

## Python 3 Script
A Python script running inside Grasshopper. Click it in this viewer to read the source; each script starts with a comment saying what it does.

## Custom Preview
Shows geometry in the Rhino viewport in a chosen colour, for the robot, fixtures, paper outline and toolpath.

## Bifocals
A plug-in component that labels every component on the canvas with its name, which makes screenshots and teaching easier. It has no effect on the robot program.
