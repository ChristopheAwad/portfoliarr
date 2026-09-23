package com.portfoliarr.app

import android.os.SystemClock
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner

/** Both activities use the same clock; opening Settings is not leaving the app. */
object AppLockSession : DefaultLifecycleObserver {
    val policy = AppLockPolicy()
    private var initialized = false

    fun initialize() {
        if (initialized) return
        initialized = true
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
    }

    override fun onStop(owner: LifecycleOwner) {
        policy.backgrounded(SystemClock.elapsedRealtime())
    }
}
