import time
from typing import Dict, Tuple, Optional

class AttentionAnalyzer:
    def __init__(self):
        self.student_states: Dict[str, dict] = {}
        
        print("=" * 80)
        print("✅ ULTRA SIMPLE ALERT SYSTEM INITIALIZED")
        print("=" * 80)
        print("RULE: attentive = NO ALERT")
        print("RULE: looking_away = INSTANT ALERT")
        print("RULE: drowsy = INSTANT ALERT")
        print("RULE: no_face = INSTANT ALERT")
        print("=" * 80)
        
    def reset_student_tracking(self, student_id: str):
        if student_id in self.student_states:
            del self.student_states[student_id]
            print(f"🧹 Reset: {student_id[:10]}...")
    
    def analyze_attention(self, student_id: str, landmark_data: dict) -> Tuple[str, float, dict]:
        if student_id not in self.student_states:
            self.student_states[student_id] = {
                'current_status': 'attentive',
                'alert_active': False,
                'last_update': time.time()
            }
        
        state = self.student_states[student_id]
        status = landmark_data.get('status', 'attentive')
        
        state['current_status'] = status
        state['last_update'] = time.time()
        
        return status, 1.0, {'status': status}
    
    def generate_alert(self, student_id: str, student_name: str, status: str, analysis: dict) -> Optional[dict]:
        """
        ULTRA SIMPLE LOGIC:
        - NOT attentive + NO alert → SEND ALERT
        - IS attentive + alert active → CLEAR ALERT
        """
        
        if student_id not in self.student_states:
            return None
        
        state = self.student_states[student_id]
        alert_active = state['alert_active']
        
        print("=" * 80)
        print(f"🔍 ALERT CHECK: {student_name}")
        print(f"   Current Status: {status.upper()}")
        print(f"   Alert Active: {alert_active}")
        print("=" * 80)
        
        # CASE 1: NOT ATTENTIVE + NO ALERT → SEND ALERT
        if status != 'attentive' and not alert_active:
            state['alert_active'] = True
            
            print("🚨" * 40)
            print(f"🚨 ALERT GENERATED: {student_name} - {status.upper()}")
            print("🚨" * 40)
            
            if status == 'looking_away':
                message = f"⚠️ {student_name} is looking away"
                severity = 'medium'
            elif status == 'drowsy':
                message = f"😴 {student_name} appears drowsy"
                severity = 'high'
            elif status == 'no_face':
                message = f"❌ {student_name} - no face detected"
                severity = 'medium'
            else:
                message = f"⚠️ {student_name} needs attention"
                severity = 'medium'
            
            return {
                'alert_type': status,
                'student_id': student_id,
                'message': message,
                'severity': severity,
                'timestamp': time.time()
            }
        
        # CASE 2: IS ATTENTIVE + ALERT ACTIVE → CLEAR ALERT
        if status == 'attentive' and alert_active:
            state['alert_active'] = False
            
            print("✅" * 40)
            print(f"✅ ALERT CLEARED: {student_name}")
            print("✅" * 40)
            
            return {
                'alert_type': 'clear_alert',
                'student_id': student_id
            }
        
        # CASE 3: NO CHANGE
        return None

analyzer = AttentionAnalyzer()