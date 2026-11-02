function [ m,a,P1] = Fit0_24McIllwrath2012( P1onP24,G )

% function determines tanh interpolation coefficients given one hour 24hr
% depth ratio and 24hr relative gradient




% interval halving 
    x1=0.0000000001;
    y1=local_McIll(P1onP24,G,x1);
    
    x3=0.5;
    y3=local_McIll(P1onP24,G,x3);
    
    if sign(y1)~=sign(y3);
          
        y2=100000;
        n1=0
        while abs(y2/G)>0.000001& n1<100;
            n1=n1+1;
            x2=(x1+x3)/2;
            [y2]=local_McIll(P1onP24,G,x2);
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
        [Err,m]=local_McIll(P1onP24,G,a);
        P1=(a+1/24)^m;
    else
       disp('Starting out of range in Fit0_24ATan2012')
       pause
        
    end
    
    function [Err,m]=local_McIll(P1onP24,G,a);
        
        Err=log(P1onP24)/log((a+1/24)/(a+1))/(a+1)-G
        m=G*(a+1)
        
