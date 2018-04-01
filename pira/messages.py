import collections
import io
import struct

# Measurement conversion configuration.
MeasurementConfig = collections.namedtuple('MeasurementConfig', ['log_type', 'conversion'])
MeasurementData = collections.namedtuple('MeasurementData', ['count', 'average', 'min_value', 'max_value'])


def get_measurement_data(boot, timestamp, measurement):
    values = boot.log.query(timestamp, measurement.log_type, only_numeric=True)
    converter = measurement.conversion or int

    # Compute statistics.
    if values:
        return MeasurementData(len(values), converter(sum(values) / len(values)), converter(min(values)), converter(max(values)))
    else:
        return

def create_measurements_message(boot, timestamp, measurements):
    """Create measurements report message.

    Message format (network byte order):
    - 2 bytes: unsigned integer, number of measurements
    - 2 bytes: unsigned integer, average
    - 2 bytes: unsigned integer, min
    - 2 bytes: unsigned integer, max

    In case there is no measurements to report in the given time
    interval, None is returned.

    :param boot: Boot instance
    :param timestamp: Measuerements start timestamp
    :param measurements: List of measurement types to include, where each
        element is a MeasurementConfig instance
    """
    have_measurements = False
    message = io.BytesIO()
    for config in measurements:
        # Compute statistics.
        data = get_measurement_data(boot, timestamp, config)

        message.write(struct.pack('!HHHH', data.count, data.average, data.min_value, data.max_value))

    if not have_measurements:
        return

    message = message.getvalue()
    return message
