function [Qe,Phi]=MDR_Design_Q2012(Pe,De,Lag)

% Function determines cummulative outflow(mm) between 0 and De associated with uniform input of
% duration De, and total excess depth of Pe, input rate Pe/De.



Phi=1-(Lag/De)*(1-exp(-De/Lag));
Qe=Phi*Pe;
