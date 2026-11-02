function [P,Pe,Q,dQdD,d2QdD2,De]=MDR_Design_P_Pe_Q2012(a,P1onP24,ARI,D,ILa,Fo,Emax,Lag)

% Function determines key MDR parameters at a prescribed duration & ARI

% Build 2012 wjc meynink 19 May 2011
% Last mod wjcm 26may2012

% VARIABLES LIST
%
% a           - Multiday design rainfall curve parameter array.
% D           - Duration (days)
% ILa         - Catchment initial loss factor(-), as fraction of initial Fo
% Fo          - Initial/starting deficit(mm)
% Emax        - Max deficit growth rate(mm/d)
% Lag         - Catchment(s) lag (days)
% ARI         - Design Average Recurrence interval(a)


[P,dPdD]=MDR_DesignRainfall2012(a,P1onP24,ARI,D);
Du=1.02*D;
[Pu]=MDR_DesignRainfall2012(a,P1onP24,ARI,Du);
Dl=0.98*D;
[Pl]=MDR_DesignRainfall2012(a,P1onP24,ARI,Dl);

[Peu,Deu,cu]=MDR_Design_Pe2012(Pu,Du,ILa,Fo,Emax);
[Pe,De,c]=MDR_Design_Pe2012(P,D,ILa,Fo,Emax);
[Pel,Del,cl]=MDR_Design_Pe2012(Pl,Dl,ILa,Fo,Emax);

[Qeu]=MDR_Design_Q2012(Peu,Deu,Lag);
[Q,Phi]=MDR_Design_Q2012(Pe,De,Lag);
[Qel]=MDR_Design_Q2012(Pel,Del,Lag);

dQdD=(Qeu-Qel)/(Du-Dl);

d2QdD2=((2*(Qeu-Q)/(Du-Dl))-(2*(Q-Qel)/(Du-Dl)))/((Du-Dl)/2) ;

