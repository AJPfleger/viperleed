# -*- coding: utf-8 -*-
"""
Created on Tue Dec  3 13:39:04 2019

@author: FF

Class storing properties and data of a beam
"""

#import tleedmlib as tl
from fractions import Fraction
import math

class Beam:
    """Has indices h,k and values as a function of energy. Initialize with
    h,k as tuple of 2 floats. Use 'maxdenom' to control the maximum value
    for the denominator."""
    def __init__(self,hk,maxdenom=99,lwidth=2):
        if all([isinstance(v, Fraction) for v in hk]):
            self.hkfrac = hk
            self.hk = (float(hk[0]), float(hk[1]))
        else:
            self.hk = hk
            self.hkfrac = (Fraction(hk[0]).limit_denominator(maxdenom),
                           Fraction(hk[1]).limit_denominator(maxdenom))
        self.lwidth = lwidth    # width of each component of the label
                                # total width = 2*lwidth+3
        self.intens = {} # intensity for each energy
        self.label = self.getLabel()
    
    def updateIndex(self,hk,maxdenom=99):
        """Keep values but change indices"""
        if all([isinstance(v, Fraction) for v in hk]):
            self.hkfrac = hk
            self.hk = (float(hk[0]), float(hk[1]))
        else:
            self.hk = hk
            self.hkfrac = (Fraction(hk[0]).limit_denominator(maxdenom),
                           Fraction(hk[1]).limit_denominator(maxdenom))
        self.label = self.getLabel()
        
    def getLabel(self):
        """Returns a string of format '( 1/2 | -1   )', where a,b in '(a|b)'
        are justified to at least the given width. If h or k end up longer, 
        the width of the other one will also be changed."""
        l = ""
        i = 0
        while i < 2:
            if i == 0:
                wl = math.ceil((self.lwidth-1)/2)    #width for numerator
            v = self.hkfrac[i]
            if v.denominator == 1:
                s = str(v.numerator).rjust(max(2,wl)) # can use more space
            else:
                s = str(v.numerator).rjust(wl)+"/"+str(v.denominator)
            s = s.ljust(self.lwidth)
            if len(s) > self.lwidth:
                self.lwidth = len(s)
                i = -1     #start over
            elif i == 0:
                l = "("+s+"|"
            else:
                l += s + ")"
            i += 1
        return l

    def normMax(self):
        """Normalizes the beam to maximum, i.e. sets the highest value to 
        1.0 and rescales the others accordingly."""
        if len(self.intens.values()) > 0:
            m = max(self.intens.values())
            if m > 0:
                for en in self.intens:
                    self.intens[en] /= m
                    
    def isEqual(self, beam, eps=1e-4):
        """Checks whether the beam is equal to another beam with a given 
        tolerance. Returns True or False."""
        if (abs(self.hk[0] - beam.hk[0]) < eps 
                and abs(self.hk[1] - beam.hk[1]) < eps):
            return True
        return False
        
    def isEqual_hk(self, hk, eps=1e-4):
        """Checks whether the beam hk is equal to a tuple hk with a given 
        tolerance. Returns True or False."""
        hk = [float(v) for v in hk]  # in case Fractions were passed
        if (abs(self.hk[0] - hk[0]) < eps 
                and abs(self.hk[1] - hk[1]) < eps):
            return True
        return False