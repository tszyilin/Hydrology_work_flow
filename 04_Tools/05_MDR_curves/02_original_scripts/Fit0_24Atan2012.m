
function [ m,a,P1] = Fit0_24Atan2012( P1onP24,G )

% function determines atan interpolation coefficients given one hour 24hr
% depth ratio and 24hr relative gradient

% VARIABLES LIST

% a             - Six parameter MDR algorithm parameters
% P1onP24zero   - Hypothetical One to 24 hour depth ratio as P24->0
% ARI           - Average recurrence interval(yrs)
% Dhrs          - Design burst duration
% Beta          - P1onP24 exponential decay coeff 
% G             - Ratio of gradient to depth at 24hrs (1/days)



% interval halving 
    x1=0.01;
    y1=local_ATan(P1onP24,G,x1);
    
    x3=10;
    y3=local_ATan(P1onP24,G,x3);
    
    if sign(y1)~=sign(y3);
          
        y2=100000;
        n1=0;
        while abs(y2/G)>0.000001& n1<100;
            n1=n1+1;
            x2=(x1+x3)/2;
            [y2]=local_ATan(P1onP24,G,x2);
            % pause
            if sign(y1)==sign(y2);
                y1=y2;
                x1=x2;
            else
                y3=y2;
                x3=x2;
            end
        end
            
        a=x2;
        [Err,m]=local_ATan(P1onP24,G,a);
        P1=atan(a/24/60)^m;
    else
       disp('Starting out of range in Fit0_24ATan2012')
       x1,y1
       x3,y3
       pause
        
    end
    
    function [Err,m]=local_ATan(P1onP24,G,a);
        
        m=log(P1onP24)/log(atan(a/24)/atan(a));
        Err=m*a/atan(a)/(1+a*a)-G;
        
