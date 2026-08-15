#!/usr/bin/env python3

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    package_share = get_package_share_directory('robocon_2027_gazebo')
    gazebo_ros_share = get_package_share_directory('gazebo_ros')
    world = os.path.join(package_share, 'worlds', 'robocon_2027_classic.world')

    return LaunchDescription([
        DeclareLaunchArgument(
            'gui', default_value='true',
            description='Set to false to run Gazebo without the client'),
        SetEnvironmentVariable('GAZEBO_MODEL_PATH', package_share),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(gazebo_ros_share, 'launch', 'gazebo.launch.py')),
            launch_arguments={
                'world': world,
                'gui': LaunchConfiguration('gui'),
            }.items(),
        ),
    ])
