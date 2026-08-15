#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash
# ROS 2 Humble's ament tools must use the system Python, not Conda Python.
export PATH=/usr/bin:/bin:$PATH

cd "$(dirname "${BASH_SOURCE[0]}")"

colcon build --packages-select robocon_2027_gazebo
source install/setup.bash
PACKAGE_SHARE=$(ros2 pkg prefix robocon_2027_gazebo)/share/robocon_2027_gazebo
export GAZEBO_MODEL_PATH="$PACKAGE_SHARE:${GAZEBO_MODEL_PATH:-}"
echo "build OK -> $PACKAGE_SHARE"
echo "classic world -> $PACKAGE_SHARE/worlds/robocon_2027_classic.world"
