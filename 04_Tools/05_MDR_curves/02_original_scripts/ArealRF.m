function [Ka] = ArealRF(CatA,ARI,Dhrs)

% AR&R Pilbra Areal reduction factor
% CatA = km^2
D=60*Dhrs;
P=1/ARI;

% For Northern Coastal AR&R Zone
a=0.326;
b=0.223;
c=0.442;
d=0.323;
e=0.0013;
f=0.580;
g=-0.374;
h=0.013;
i=-0.0015;

Ka=(1-a*(CatA^b-c*log10(D))*D^(-d)+e*CatA^f*D^g*(0.3+log10(P)+h*10^(i*CatA*D/1440)*(0.3+log10(P))));

Ka=min(1,Ka);