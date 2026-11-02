function [NashEff,RMSE,Rsqd,Dbias,m]=NashSutcliff(Obs,Prd)
% Function determines Nash-Sutcliff criterion & other measures of model
% performance.
[A, B, R, Vx, Vy, Vyx]=BestFitLine (Obs,Prd,1)
Rsqd=R^2
Dbias=A/mean(Obs)
% pause
m=length(Obs);
rmse=0.0;
for i=1:m
rmse=rmse+(Obs(i)-Prd(i))^2;
end
NashEff=1-rmse/m/var(Obs);
RMSE=sqrt(rmse/m);
