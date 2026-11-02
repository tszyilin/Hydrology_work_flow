function [A, B, R, Vx, Vy, Vyx]=BestFitLine (XX, YY,NType)

% Sub Program determines line of best fit through X,Y for the selected model
% NType, options are:

%   1 - Linear Y = a+bX
%   2 - Power  Y = a.X^b
%   3 - Exponential Y = a.EXP(bX)
%   4 - Exponential Y = a.b^X
%   5 - Log  Y=a + b.Ln(X)

% Ver 1 Rev B  WJC Meynink Nov 73
% Last Mod WJCM 7 Jun 07

K=length(XX);
X=[];
Y=[]; 
    switch NType
    case 1  % Linear
        X = XX;
        Y = YY;
    case 2  % Power
        X = log(XX);
        Y = log(YY);
    case 3, 4 % Exponential
        X = XX;
        Y= log(YY);
    case 5 % log
        X = log(XX);
        Y = YY;
    
        otherwise
            'lost'
        pause
        
    end


XSum = sum(X);
YSum = sum(Y);
XYSum = sum(X.*Y);
XXSum = sum(X.*X);
YYSum = sum(Y.*Y);

Zx = K * XXSum - XSum * XSum;
Zy = K * YYSum - YSum * YSum;
R = (K * XYSum - XSum * YSum) / sqrt(Zx * Zy);
Vx = Zx / K / (K - 1);
Vy = Zy / K / (K - 1);
A = (YSum * XXSum - XYSum * XSum) / Zx;
B = (K * XYSum - YSum * XSum) / Zx;
Vyx = (K - 1) * (Vy - B * B * Vx) / (K - 2);

switch NType
    case 1
    % No Change
case 2
A = exp(A);
case 3
A = exp(A);
case 4
A = exp(A);
B = exp(B);
otherwise
end

