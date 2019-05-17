import numpy


def bollinger_bands(data, period, devs):
    data = list(map(lambda x: x[4], data))[-period:]
    ma = numpy.mean(data)
    st_dev = numpy.std(data)
    return [ma - st_dev * devs, ma, ma + st_dev * devs]
