function [ P,dPdD ] = Interp0_24HrATan2012(a,P1onP24zero,ARI,Dhrs )%(a,P1onP24zero,Beta,ARI,Dhrs )

% Funtion uses Gradient at 24hrs and P1hr/P24hr ratio to interpolate
% sub 24hr rainfalls using the arc Tan function

% VARIABLES LIST

% a             - Six parameter MDR algorithm parameters
% P1onP24zero   - Hypothetical One to 24 hour depth ratio as P24->0
% ARI           - Average recurrence interval(yrs)
% Dhrs          - Design burst duration
% Beta          - P1onP24 exponential decay coeff 
% G             - Ratio of gradient to depth at 24hrs (1/days)

D=Dhrs/24;
Beta=-0.000557;

        P24hr=a(1)+a(4)*log(ARI);
        P1onP24=(P1onP24zero-1/24)*exp(Beta*P24hr)+(1/24);
        dPdT24=a(2)*a(3)+ a(5)*a(6)*log(ARI);
        G=dPdT24/P24hr;
        
        [ m,a] = Fit0_24Atan2012( P1onP24,G );
        
        Pratio=(atan(a*D)^m)/atan(a)^m;
        P=P24hr*Pratio;
        
        dPdD=P24hr*m*(a/(1+a*a))*atan(a*D)^(m-1);
       