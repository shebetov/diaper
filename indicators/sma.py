import numpy


def sma(data, period, offset=0):
    data = list(map(lambda x: x[4], data))
    if offset > 0:
        return numpy.mean(data[-period-offset:-offset])
    else:
        return numpy.mean(data[-period:])
