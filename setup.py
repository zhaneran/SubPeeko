"""Run the vocabulary check in package build trees, without editing the checkout."""

from pathlib import Path
from runpy import run_path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

refresh = run_path("vocabulary_build.py")["refresh"]


class BuildPy(build_py):
    def run(self):
        super().run()
        refresh(Path(self.build_lib) / "subpeeko" / "data")


class SDist(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        refresh(Path(base_dir) / "src" / "subpeeko" / "data")


setup(cmdclass={"build_py": BuildPy, "sdist": SDist})
