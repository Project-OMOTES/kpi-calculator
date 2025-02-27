#  Copyright (c) 2023. {cookiecutter.cookiecutter.maintainer_name}}
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Test script for python template."""
from datetime import datetime
import unittest
from kpicalculator import kpicalculator


class MyTest(unittest.TestCase):
    def tearDown(self) -> None:
        import logging
        from importlib import reload

        logging.shutdown()
        reload(logging)
        return super().tearDown()

    def test__testable_function__is_correct(self) -> None:
        # Arrange
        current_time = datetime(1970, 1, 1, 13, 00)

        # Act
        result = kpicalculator.testable_function(current_time)

        # Assert
        expected_result = datetime(1970, 1, 1, 14, 00)
        self.assertEqual(expected_result, result)

    def test_start_app_info(self) -> None:
        try:
            kpicalculator.start_app(loglevel="INFO", colors=True)
        except Exception as e:
            self.fail(f"kpicalculator.start_app() raised an exception: {e}")

    def test_start_app_debug(self) -> None:
        try:
            kpicalculator.start_app(loglevel="DEBUG", colors=False)
        except Exception as e:
            self.fail(f"kpicalculator.start_app() raised an exception: {e}")

    def test_start_app_wrong_logtype(self) -> None:
        with self.assertRaises(ValueError):
            kpicalculator.start_app(loglevel="WRONG_LOG_TYPE", colors=False)
