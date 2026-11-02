function [ P,dPdD ] = Interp0_24HrTanh2012(a,P1onP24,ARI,Dhrs )

% Funtion uses Gradient at 24hrs and P1hr/P24hr ratio to interpolate
% sub 24hr rainfalls using a Tanh function

        D=Dhrs/24
        P24hr=a(1)+a(4)*log(ARI)
        dPdT24=a(2)*a(3)+ a(5)*a(6)*log(ARI)
        G=dPdT24/P24hr
        
        [ m,aa] = Fit0_24Tanh2012( P1onP24,G )
        
        Pratio=(tanh(aa*D)^m)/tanh(aa)^m
        P=P24hr*Pratio
        
        dPdD=P24hr*aa*m*sech(aa*D)*sech(aa*D)*tanh(aa*D)^(m-1)
        
       