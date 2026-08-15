cmake_minimum_required(VERSION 3.8)
project(robocon_2027_gazebo)

set(Python3_EXECUTABLE /usr/bin/python3 CACHE FILEPATH "System Python for ament" FORCE)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY robocon_2027_field worlds
  DESTINATION share/${PROJECT_NAME}
)

install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
