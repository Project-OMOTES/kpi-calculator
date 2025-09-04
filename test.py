from src.kpicalculator.exceptions import ValidationError
from src.kpicalculator.common.constants import RFC_1035_HOSTNAME_LIMIT, MAX_TIME_SERIES_LENGTH

class Credentials:
    def __init__(self, host):
        self.host = host

credentials = Credentials("a" * 101)

if len(credentials.host) > RFC_1035_HOSTNAME_LIMIT:
    raise ValidationError(
        f"Hostname too long: {len(credentials.host)} > {RFC_1035_HOSTNAME_LIMIT}"
    )

field_name = "test"
time_series_data = [1] * 10001

if len(time_series_data) > MAX_TIME_SERIES_LENGTH:
    raise ValidationError(
        f"{field_name} too long: {len(time_series_data)} > {MAX_TIME_SERIES_LENGTH}"
    )
