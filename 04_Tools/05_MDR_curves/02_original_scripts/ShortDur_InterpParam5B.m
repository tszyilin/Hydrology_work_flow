function [n]=ShortDur_InterpParam5B(a,dPdD1donP1d)

% Function ShortDur_InterpParam determines 0 - 24hr interpolation function
% parameters from the MDR curve using interval halving.
% 
% The 0 to 24 hr rainfall as ratio Y of the 24hr total is given by
% Y= [(a+t)/(a+1)]^n
% with parameters a & n evaluated in this function

% Build 01 wjc Meynink 23 Nov 07
% Last mod wjcm 4 Aug 09 

% VARIABLES LIST
%
% a,n

n=(a+1)*(1-dPdD1donP1d);
