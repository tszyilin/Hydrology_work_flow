function [Pe,De,c]=MDR_Design_Pe2012(P,D,ILa,Fo,Emax)

% Function determines rainfall excess for rainfall/duration pair and
% prescribed loss model parameters.

 F=Fo+max(0,D-1)*Emax;
 Pstar=P-ILa*Fo;
 X=Pstar/F;

        
if Pstar>0
    c=(tanh(X))^2;
    Pe=(Pstar-F*tanh(X));
    De=(1-ILa*Fo/P)*D;
else
    Pe=0.0;
    De=0.0;
end
        

