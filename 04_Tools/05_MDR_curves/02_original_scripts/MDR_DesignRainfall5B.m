function [P,P24hr,dPdD]=MDR_DesignRainfall5B(a,ARI,D)

% Function determines design rainfall for prescribed curve and given
% duration and ARI. MDR curve is of form
% MDR =  Frequency Function x Duration Function
% where: FrequencyFunction = a(2)+ a(3)*log(ARI)^a(4);
%        DurationFunction =  {(a(1)+sqrt(Dur(I))+a(5)*Dur(I};
% The 0 to 24 hr rainfall as ratio Y of the 24hr total is given by
% Y= t.[(a+1)/(a+t)]^n
%
% Build 01 wjcm 7 Feb 07 
% last mod wjcm 15 aug 08

b=5/1440;

FF = a(2) + a(3) * log(ARI)^a(4);
DF=a(1)+1+a(5);
P24hr=FF*DF;


if D<1
        % Use 0-24hr interpolation function
        FF = a(2) + a(3) * log(ARI)^a(4);
        DF=a(1)+1+a(5);
        P24hr=FF*DF;
        dPdT=FF*(0.5+a(5));
        dPdT24onP24=dPdT/P24hr;
  
        [n]=ShortDur_InterpParam5B(b,dPdT24onP24); 
       
        
        y=D*((b+1)/(b+D))^n;
        yl=0.99*D*((b+1)/(b+0.99*D))^n;
        yh=1.01*D*((b+1)/(b+1.01*D))^n;
        dydD=(yh-yl)/0.02/D;
        P=y*P24hr;
        dPdD=dydD*P24hr;
       
    else
        FF = a(2) + a(3) * log(ARI)^a(4);
        DF=a(1)+sqrt(D)+a(5)*D;
        P=FF*DF;
        dPdD=FF*(0.5/sqrt(D)+a(5));
        
    end
    

