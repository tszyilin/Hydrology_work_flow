function [P,P24hr,dPdD,Z]=MDR_DesignRainfall2012(a,P1onP24zero,ARI,D)

% Function determines design rainfall for prescribed 2012 curve and given
% duration and ARI.
% MDR curve is of form:-  MDR =  AA + BB.Ln(ARI)
%                             where: AA= a(1)+ a(2)*(D^a(3)-1);
%                                    BB= a(4)+ a(5)*(D^a(6)-1);
%
% The 0 to 24 hr rainfall as ratio Y of the 24hr total is given by
% Y= (1-G+G*D)*(sin(pi*D/2))^m   with the exponent m set from the
% P1hr/P24hr ratio
%
% Build 01 wjcm 1 Mar 2012 
% last mod wjcm 5 Mar 12

% VARIABLES LIST
%
% a           - array of MDR curve coefficients
% P1onP24     - Ratio of 1hr to 24hr rainfall at prescribed ARI(-)
% P1onP24zero   - Hypothetical One to 24 hour depth ratio as P24->0
% ARI         - Average recurrance interval(yrs)
% D           - Design event duration(days)
%
% P           - Rainfall depth(mm) for duration D, at prescribed ARI
% P24hr       - Unrestricted 24 hr rainfall(mm) at prescribed ARI
% dPdD        - Rate of change of rainfall with duration at D(mm/day) at prescribed ARI
% Z           - Design rainfall critical duration Rainfall curve ordinate (-)

P24hr=a(1)+a(4)*log(ARI);
Beta=-0.000557;

if D<1
        % Use 0-24hr interpolation function
        P24hr=a(1)+a(4)*log(ARI);
        P1onP24=(P1onP24zero-1/24)*exp(Beta*P24hr)+(1/24);
        dPdT24=a(2)*a(3)+ a(5)*a(6)*log(ARI);
        G=dPdT24/P24hr;
        
        a,P1onP24,ARI,24*D
        [ P,dPdD ] = Interp0_24HrATan2012(a,P1onP24,ARI,24*D);
    
else   % D>1 day
        AA=a(1) + a(2) *(D^a(3)-1);
        BB=a(4) + a(5)*(D^a(6)-1);
        P=AA+BB*log(ARI);
        dPdD=a(2)*a(3)*D^(a(3)-1)+a(5)*a(6)*(D^(a(6)-1))*log(ARI);
end
    
Z=1-dPdD/(P/D);   
