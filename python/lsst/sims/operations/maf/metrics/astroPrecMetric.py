import numpy as np
from .baseMetric import BaseMetric

def m52snr(m,m5):
    """find the SNR for a star of magnitude m obsreved
    under conditions of 5-sigma limiting depth m5 """
    snr = 5.*10.**(-0.4*(m-m5))
    return snr

class AstroPrecMetric(BaseMetric):
    """Calculate the average astrometric precision given a set of observations """
    def __init__(self, metricName='AstroPrecMetric', m5col='5sigma_modified', seeingcol='finSeeing', units='mas', mag=20., atm_limit=0.01, **kwargs):
        """ """
        cols=[m5col,seeingcol]
        super(AstroPrecMetric,self).__init__(cols,metricName,units=units, **kwargs)
        self.seeingcol = seeingcol
        self.m5col = m5col
        self.units=units
        self.metricDtype = 'float'
        self.atm_limit=atm_limit
        self.mag = mag
    
    def run(self, dataSlice):
        result = dataSlice[self.seeingcol]/m52snr(self.mag,dataSlice[self.m5col])
        result = (result**2+self.atm_limit**2)**0.5
        result = result.mean()*1e3 # Convert from arcsec to mas
        return result
    
