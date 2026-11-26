import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:lectio_mobile/main.dart';

void main() {
  testWidgets('Landing screen renders without a configured service', (
    WidgetTester tester,
  ) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const LectioApp());
    await tester.pump();
    expect(find.byType(LectioApp), findsOneWidget);
  });
}
