# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

url = "https://repos.digie35.com/python"
setup(
    name='digie35_ctrl',
    version='0.8.1',
    description='Digie35 Control package',
    long_description=readme,
    author='Tomas Mandys',
    author_email='tma@2p.cz',
    url='https://github.com/tmandys/digie35-python.git',
    license=license,
    packages=find_packages(
        where=".",
        exclude=('tests', 'docs'),
    ),
    project_urls={
        "changelog": url+"/CHANGELOG.md",

    },
    #include_package_data=True,
    package_data={
        "digie35": [
            "html/*.html",
            "html/*.css",
            "html/*.js",
            "html/images/*",
            "systemd/*.service",
            "cameras/*",
            "desktop/*",
            "images/*",
            "nginx/*",
            "preset/*.xmp",
            "file_template/*"
        ],
    },
    entry_points={
        "console_scripts": [
            "digie35_server = digie35.digie35_server:main",
            "digie35_test_server = digie35.digie35_test_server:main",
            "digie35_install = digie35.install:main",
            "digie35_upgrade = digie35.upgrade:main",
            "digie35_board_tool = digie35.board_tool:main",
            "digie35_log = digie35.log_term:main",
            "digie35_image_analyzer = digie35.image_analyzer:main",
        ],
    },
    install_requires = [
        #"nose",
        #"sphinx",
        "pyyaml",
        "RPi.GPIO",
        "smbus",
        "smbus2",
        "netifaces",
        "rpi_hardware_pwm",
        "websockets",
        "gphoto2",
        "gpiozero",
        "evdev",
        "lxml",
        "simpleeval",
		# installed via apt get
        #"scipy",
        #"numpy",
        #"opencv-python",
        #"configparser",
    ],
    scripts = [
        "digie35/digie35_lxde-pi-shutdown-helper",
    ],
)

