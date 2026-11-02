function [P,dPdD ] = Interp0_24HrSin2012(a,P1onP24,ARI,Dhrs )

% Funtion uses Gradient at 24hrs and P1hr/P24hr ratio to interpolate
% sub 24hr rainfalls using a sin function

D=Dhrs/24
        P24hr=a(1)+a(4)*log(ARI)
        dPdT24=a(2)*a(3)+ a(5)*a(6)*log(ARI);
        G=dPdT24/P24hr;
        
        if P1onP24<(1-G)  % solution possible
            Y1=1-23*G/24
            m=log(P1onP24/Y1)/log(sin(pi/48))
            z=sin(pi*D/2)
            Y=((1-G)+G*D)*z^m
            P=Y*P24hr
            z=sin(pi*D/2)
            y=(1-G)+G*D
            dPdD=y*m*z^(m-1)*cos(pi*D/2)*(pi/2)+G*z^m
            dPdD=dPdD*P24hr
            
        else
             disp('Solution not possible - reduce P1/P24')
             P=-1
             dPdD=-1
        end
